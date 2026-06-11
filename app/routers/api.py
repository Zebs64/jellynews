"""API d'administration (toutes les routes exigent une session valide)."""
import csv
import io
import ipaddress
import json
import re
import zoneinfo

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from .. import auth, database, scheduler
from ..services import jellyfin, llm, mailer, newsletter

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_user)])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_LOGO_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 Mo


# --------------------------------------------------------------- settings --
@router.get("/settings")
def get_settings():
    settings = database.get_settings()
    settings["_next_run"] = scheduler.next_run_iso()
    return settings


def _validate_settings(payload: dict) -> None:
    if payload.get("timezone"):
        try:
            zoneinfo.ZoneInfo(str(payload["timezone"]))
        except Exception:
            raise HTTPException(400, f"Fuseau horaire inconnu : {payload['timezone']}")
    if "trusted_proxies" in payload:
        for entry in str(payload["trusted_proxies"]).split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError:
                raise HTTPException(400, f"IP ou CIDR invalide : {entry}")


@router.post("/settings")
def save_settings(payload: dict = Body(...)):
    _validate_settings(payload)
    database.set_settings(payload)  # filtré par la liste blanche DEFAULTS
    scheduler.reschedule()          # prise en compte immédiate du nouveau cron
    return {"ok": True, "next_run": scheduler.next_run_iso()}


@router.get("/timezones")
def list_timezones():
    return sorted(zoneinfo.available_timezones())


# ------------------------------------------------------------------- logo --
@router.post("/logo")
async def upload_logo(file: UploadFile = File(...)):
    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in (file.filename or "") else ""
    if ext not in ALLOWED_LOGO_EXT:
        raise HTTPException(400, f"Extension non autorisée ({', '.join(sorted(ALLOWED_LOGO_EXT))})")
    data = await file.read()
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(400, "Logo trop volumineux (2 Mo max)")
    # Nom de fichier fixe et contrôlé : aucune injection de chemin possible.
    filename = f"logo{ext}"
    for old in database.UPLOADS_DIR.glob("logo.*"):
        old.unlink(missing_ok=True)
    (database.UPLOADS_DIR / filename).write_bytes(data)
    database.set_settings({"logo_filename": filename})
    return {"ok": True, "url": f"/uploads/{filename}"}


# ------------------------------------------------------------ subscribers --
@router.get("/subscribers")
def list_subscribers():
    return database.list_subscribers()


@router.get("/subscribers/export")
def export_subscribers():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["email", "created_at"])
    for sub in database.list_subscribers():
        writer.writerow([sub["email"], sub["created_at"]])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=jellynews-abonnes.csv"},
    )


@router.post("/subscribers/import")
async def import_subscribers(file: UploadFile = File(...)):
    """Import tolérant : extrait toute adresse email valide du fichier
    (CSV avec ou sans en-tête, une adresse par ligne, séparateurs variés)."""
    data = (await file.read()).decode("utf-8", errors="replace")
    found = set(re.findall(r"[^@\s,;\"']+@[^@\s,;\"']+\.[^@\s,;\"']+", data))
    before = len(database.list_subscribers())
    for email in found:
        database.add_subscriber(email.lower())
    added = len(database.list_subscribers()) - before
    return {"ok": True, "found": len(found), "added": added}


@router.post("/subscribers")
def add_subscriber(payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Adresse email invalide")
    database.add_subscriber(email)
    return {"ok": True}


@router.delete("/subscribers/{sub_id}")
def delete_subscriber(sub_id: int):
    database.delete_subscriber(sub_id)
    return {"ok": True}


# ------------------------------------------------------------------- logs --
@router.get("/logs")
def list_logs():
    return database.list_logs()


# ----------------------------------------------------------- import/export --
@router.get("/settings/export")
def export_settings():
    """ATTENTION : le fichier exporté contient les secrets (SMTP, clés API)."""
    return Response(
        json.dumps(database.get_settings(), indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=jellynews-config.json"},
    )


@router.post("/settings/import")
async def import_settings(file: UploadFile = File(...)):
    try:
        payload = json.loads((await file.read()).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("le fichier doit contenir un objet JSON")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"JSON invalide : {exc}")
    known = {k: v for k, v in payload.items() if k in database.DEFAULTS}
    _validate_settings(known)
    database.set_settings(known)  # filtré par la liste blanche DEFAULTS
    scheduler.reschedule()
    return {"ok": True, "imported": len(known)}


# ---------------------------------------------------------------- archives --
@router.get("/archives")
def list_archives():
    return database.list_archives()


@router.get("/archives/{archive_id}", response_class=HTMLResponse)
def view_archive(archive_id: int):
    row = database.get_archive(archive_id)
    if not row:
        raise HTTPException(404, "Archive introuvable")
    return HTMLResponse(row["html"])


# ---------------------------------------------------------------- actions --
@router.post("/test/jellyfin")
def test_jellyfin():
    try:
        return jellyfin.test_connection(database.get_settings())
    except Exception as exc:
        raise HTTPException(502, f"Connexion Jellyfin impossible : {exc}")


@router.get("/jellyfin/libraries")
def jellyfin_libraries():
    try:
        return jellyfin.list_libraries(database.get_settings())
    except Exception as exc:
        raise HTTPException(502, f"Connexion Jellyfin impossible : {exc}")


@router.post("/test/llm")
def test_llm():
    """Génère une intro d'exemple en remontant l'erreur réelle du LLM
    (contrairement à l'envoi, qui masque l'échec derrière le texte de repli)."""
    settings = database.get_settings()
    try:
        names = [i["name"] for i in jellyfin.fetch_recent_items(settings)] or llm.SAMPLE_TITLES
    except Exception:
        names = llm.SAMPLE_TITLES  # Jellyfin pas encore configuré : titres d'exemple
    try:
        return {"ok": True, "intro": llm.request_intro(names, settings), "titles": names[:10]}
    except Exception as exc:
        raise HTTPException(502, f"Échec du LLM : {exc}")


@router.post("/test/email")
def test_email(payload: dict = Body(...)):
    to = (payload.get("to") or "").strip()
    if not EMAIL_RE.match(to):
        raise HTTPException(400, "Adresse email invalide")
    settings = database.get_settings()
    html = (
        "<div style='font-family:sans-serif;background:#0b0f14;color:#e8eef4;padding:24px;'>"
        "<h2>JellyNews — Test SMTP réussi ✔</h2>"
        "<p>Si vous lisez ceci, votre configuration SMTP fonctionne.</p></div>"
    )
    try:
        sent = mailer.send_html(settings, [to], "JellyNews — Email de test", html)
    except Exception as exc:
        raise HTTPException(502, f"Échec SMTP : {exc}")
    if not sent:
        raise HTTPException(502, "Le serveur SMTP a refusé le message")
    return {"ok": True}


@router.get("/preview", response_class=HTMLResponse)
def preview():
    """Rend la newsletter avec les vraies données Jellyfin + intro LLM."""
    settings = database.get_settings()
    try:
        context, items = newsletter.build_context(settings)
    except Exception as exc:
        raise HTTPException(502, f"Prévisualisation impossible : {exc}")
    if not items:
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:2em;'>"
            "Aucune nouveauté sur la période configurée.</p>"
        )
    return HTMLResponse(newsletter.render_html(settings, context, for_email=False))


@router.post("/send-now")
def send_now():
    try:
        return newsletter.run(trigger="manual")
    except Exception as exc:
        raise HTTPException(502, f"Échec de l'envoi : {exc}")
