"""JellyNews — point d'entrée FastAPI : pages web (setup, login, dashboard) + API."""
import ipaddress
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, database, scheduler
from .routers import api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="JellyNews", docs_url=None, redoc_url=None)

# NOTE CORS : le front est servi par la même origine que l'API, il n'y a donc
# AUCUN middleware CORS à ajouter (c'est plus sûr ainsi). Si un jour vous
# consommez l'API depuis un autre domaine, ajoutez CORSMiddleware avec une
# liste explicite d'origines — jamais "*" combiné à allow_credentials=True.

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# Le logo uploadé est servi publiquement (nécessaire pour la prévisualisation) ;
# il ne contient aucune donnée sensible.
app.mount("/uploads", StaticFiles(directory=database.UPLOADS_DIR), name="uploads")

templates = Jinja2Templates(directory=BASE_DIR / "templates" / "web")

app.include_router(api.router)


@app.on_event("startup")
def startup() -> None:
    database.init_db()
    scheduler.start()


# ------------------------------------------------------------------- pages --
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not database.has_admin():
        return RedirectResponse("/setup", status_code=303)
    user = auth.get_session_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user})


# --- First-time setup : création du compte admin à la première visite -------
@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if database.has_admin():
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@app.post("/setup")
def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    # Garde-fou : une fois l'admin créé, cette route est définitivement fermée.
    if database.has_admin():
        return RedirectResponse("/login", status_code=303)
    error = None
    if len(username.strip()) < 3:
        error = "Le nom d'utilisateur doit faire au moins 3 caractères."
    elif len(password) < 8:
        error = "Le mot de passe doit faire au moins 8 caractères."
    elif password != password_confirm:
        error = "Les deux mots de passe ne correspondent pas."
    if error:
        return templates.TemplateResponse(request, "setup.html", {"error": error}, status_code=400)
    database.create_admin(username.strip(), auth.hash_password(password))
    return RedirectResponse("/login", status_code=303)


# --- Identification du client derrière un reverse-proxy -----------------------
def _peer_is_trusted(peer: str, trusted: list[str]) -> bool:
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if peer_ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue  # entrée invalide ignorée (validée à la sauvegarde)
    return False


def _client_ip(request: Request) -> str:
    """IP réelle du client pour le rate-limiting.

    SÉCURITÉ : X-Forwarded-For n'est consulté que si « derrière un proxy »
    est activé ET que le pair direct est de confiance (trusted_proxies, ou
    n'importe quel pair si la liste est vide — acceptable uniquement quand
    seul le proxy peut joindre le conteneur). On prend la DERNIÈRE entrée de
    l'en-tête : c'est celle ajoutée par votre proxy, que le client ne peut
    pas falsifier — contrairement aux entrées précédentes.
    """
    peer = request.client.host if request.client else "?"
    settings = database.get_settings()
    if settings.get("behind_proxy") != "1":
        return peer
    trusted = [t.strip() for t in (settings.get("trusted_proxies") or "").split(",") if t.strip()]
    if trusted and not _peer_is_trusted(peer, trusted):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() or peer


# --- Rate-limiting du login --------------------------------------------------
# Anti-brute-force simple : 5 échecs par IP sur 15 minutes -> 429.
# En mémoire (réinitialisé au redémarrage), suffisant pour un service
# auto-hébergé.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures: dict[str, list[float]] = {}


def _login_blocked(ip: str) -> bool:
    now = time.monotonic()
    attempts = [t for t in _login_failures.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_failures[ip] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_login_failure(ip: str) -> None:
    _login_failures.setdefault(ip, []).append(time.monotonic())


# --- Login / logout ----------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if not database.has_admin():
        return RedirectResponse("/setup", status_code=303)
    if auth.get_session_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = _client_ip(request)
    if _login_blocked(ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Trop de tentatives. Réessayez dans 15 minutes."},
            status_code=429,
        )
    user = database.get_user(username.strip())
    if not user or not auth.verify_password(password, user["password_hash"]):
        _record_login_failure(ip)
        # Message volontairement identique que l'utilisateur existe ou non
        # (pas d'énumération de comptes).
        return templates.TemplateResponse(
            request, "login.html", {"error": "Identifiants invalides."}, status_code=401
        )
    _login_failures.pop(ip, None)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_token(user["username"]),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,        # inaccessible au JavaScript (anti-XSS)
        samesite="lax",       # bloque l'essentiel des CSRF cross-site
        # Flag Secure : réglage de l'interface (panneau Sécurité), ou env COOKIE_SECURE=1.
        secure=database.get_settings().get("cookie_secure") == "1" or auth.COOKIE_SECURE,
    )
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response


# --- Désinscription en un clic (route PUBLIQUE, token signé) ------------------
@app.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(request: Request, token: str):
    email = auth.verify_unsubscribe_token(token)
    if email is None:
        return templates.TemplateResponse(
            request, "unsubscribe.html",
            {"ok": False, "message": "Lien de désinscription invalide."},
            status_code=400,
        )
    removed = database.delete_subscriber_by_email(email)
    message = (
        f"L'adresse {email} ne recevra plus la newsletter."
        if removed
        else f"L'adresse {email} était déjà désinscrite."
    )
    return templates.TemplateResponse(
        request, "unsubscribe.html", {"ok": True, "message": message}
    )


# Désinscription en un clic « RFC 8058 » : les clients mail (Gmail…) envoient
# un POST sur l'URL du header List-Unsubscribe, sans interaction utilisateur.
@app.post("/unsubscribe/{token}")
def unsubscribe_oneclick(token: str):
    email = auth.verify_unsubscribe_token(token)
    if email is None:
        return {"ok": False}
    database.delete_subscriber_by_email(email)
    return {"ok": True}
