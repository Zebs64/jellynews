"""API d'administration (toutes les routes exigent une session valide)."""
import csv
import datetime
import html
import io
import ipaddress
import json
import re
import zoneinfo

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from .. import auth, database, scheduler
from ..services import jellyfin, llm, mailer, newsletter, newsletter_templates, urls
from ..version import APP_VERSION

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_user)])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_LOGO_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 Mo
PUBLIC_URL_SETTINGS = {
    "jellyfin_url": False,
    "jellyfin_external_url": True,
    "app_public_url": True,
}


def _validate_int_range(payload: dict, key: str, minimum: int, maximum: int) -> None:
    if key not in payload:
        return
    try:
        value = int(str(payload[key]))
    except (TypeError, ValueError):
        raise HTTPException(400, f"Champ numérique invalide : {key}")
    if value < minimum or value > maximum:
        raise HTTPException(400, f"{key} doit être compris entre {minimum} et {maximum}")


# --------------------------------------------------------------- settings --
@router.get("/settings")
def get_settings():
    settings = database.get_settings()
    settings["_next_run"] = scheduler.next_run_iso()
    settings["_app_version"] = APP_VERSION
    return settings


@router.get("/newsletter/templates")
def newsletter_template_options():
    return {
        "templates": newsletter_templates.template_options(),
        "blocks": newsletter_templates.block_options(),
        "default_template_id": newsletter_templates.DEFAULT_TEMPLATE_ID,
        "default_blocks_json": newsletter_templates.serialize_blocks(newsletter_templates.default_blocks()),
    }


@router.get("/dashboard-summary")
def dashboard_summary():
    """Résumé KISS de l'accueil admin.

    Route protégée par la dépendance globale du router : aucune métrique n'est
    exposée hors session administrateur.
    """
    settings = database.get_settings()
    logs = database.list_logs(1)
    recent_items_count: int | None = None
    recent_items_error = ""
    try:
        recent_items_count = len(jellyfin.fetch_recent_items(settings))
    except Exception:
        recent_items_error = "Nouveautés indisponibles : configurez ou testez Jellyfin."

    last_send = None
    if logs:
        log = logs[0]
        last_send = {
            "created_at": log.get("created_at"),
            "status": log.get("status"),
            "items_count": log.get("items_count", 0),
            "recipients": log.get("recipients", 0),
        }

    return {
        "next_run": scheduler.next_run_iso(),
        "lookback_days": int(settings.get("lookback_days") or 7),
        "recent_items_count": recent_items_count,
        "recent_items_error": recent_items_error,
        "subscribers_count": len(database.list_subscribers()),
        "last_send": last_send,
    }


def _validate_settings(payload: dict) -> None:
    for key, allow_empty in PUBLIC_URL_SETTINGS.items():
        if key not in payload:
            continue
        try:
            payload[key] = urls.normalize_public_http_url(
                payload[key], field=key, allow_empty=allow_empty
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
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
    _validate_int_range(payload, "smtp_batch_size", 1, 500)
    _validate_int_range(payload, "smtp_batch_pause_seconds", 0, 3600)
    try:
        normalized_newsletter = newsletter_templates.normalize_settings(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if "newsletter_template_id" in payload:
        payload["newsletter_template_id"] = normalized_newsletter["newsletter_template_id"]
    if "newsletter_blocks_json" in payload:
        payload["newsletter_blocks_json"] = normalized_newsletter["newsletter_blocks_json"]


def _parse_iso_datetime(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, f"Champ datetime invalide : {field}")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        datetime.datetime.fromisoformat(normalized)
    except ValueError:
        raise HTTPException(400, f"Champ datetime invalide : {field}")
    return value.strip()


def _int_non_negative(value: object, field: str) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(400, f"Champ numérique invalide : {field}")
    if number < 0:
        raise HTTPException(400, f"Champ numérique invalide : {field}")
    return number


def _text(value: object, field: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise HTTPException(400, f"Champ texte invalide : {field}")
    if required and not value.strip():
        raise HTTPException(400, f"Champ texte invalide : {field}")
    return value


def _normalize_settings(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(400, "La section settings doit être un objet JSON")
    known = {k: v for k, v in payload.items() if k in database.DEFAULTS}
    if not str(known.get("jellyfin_url") or "").strip():
        # Backups exportés avant toute configuration contiennent la valeur par
        # défaut vide. À l'import, on la traite comme absente pour conserver
        # l'idempotence sans autoriser une URL Jellyfin vide côté sauvegarde API.
        known.pop("jellyfin_url", None)
    _validate_settings(known)
    return known


def _normalize_subscribers(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        raise HTTPException(400, "La section subscribers doit être une liste")
    now = datetime.datetime.now().isoformat(timespec="seconds")
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise HTTPException(400, f"Abonné invalide à l'index {index}")
        email = str(row.get("email") or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(400, f"Adresse email invalide à l'index {index}")
        created_at = row.get("created_at") or now
        if created_at != now:
            created_at = _parse_iso_datetime(created_at, f"subscribers[{index}].created_at")
        if email in seen:
            continue
        seen.add(email)
        normalized.append({"email": email, "created_at": created_at})
    return normalized


def _normalize_send_logs(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        raise HTTPException(400, "La section send_logs doit être une liste")
    normalized: list[dict] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise HTTPException(400, f"Entrée send_logs invalide à l'index {index}")
        normalized.append({
            "created_at": _parse_iso_datetime(row.get("created_at"), f"send_logs[{index}].created_at"),
            "trigger": _text(row.get("trigger"), f"send_logs[{index}].trigger"),
            "status": _text(row.get("status"), f"send_logs[{index}].status"),
            "items_count": _int_non_negative(row.get("items_count", 0), f"send_logs[{index}].items_count"),
            "recipients": _int_non_negative(row.get("recipients", 0), f"send_logs[{index}].recipients"),
            "detail": _text(row.get("detail", ""), f"send_logs[{index}].detail", required=False)[:2000],
        })
    return normalized


def _normalize_archives(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        raise HTTPException(400, "La section archives doit être une liste")
    normalized: list[dict] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise HTTPException(400, f"Archive invalide à l'index {index}")
        source_html = _text(row.get("html"), f"archives[{index}].html")
        normalized.append({
            "created_at": _parse_iso_datetime(row.get("created_at"), f"archives[{index}].created_at"),
            "subject": _text(row.get("subject"), f"archives[{index}].subject"),
            "items_count": _int_non_negative(row.get("items_count", 0), f"archives[{index}].items_count"),
            "recipients": _int_non_negative(row.get("recipients", 0), f"archives[{index}].recipients"),
            "html": html.escape(html.unescape(source_html), quote=False),
            "_source_html": source_html,
        })
    return normalized


def _prepare_backup_import(payload: dict) -> dict:
    if "schema_version" not in payload:
        return {
            "settings": _normalize_settings(payload),
            "subscribers": [],
            "send_logs": [],
            "archives": [],
        }
    schema_version = payload.get("schema_version")
    if schema_version not in (2, "2"):
        raise HTTPException(400, f"Schéma de sauvegarde non supporté : {schema_version}")
    nested = payload.get("data")
    source = nested if isinstance(nested, dict) else payload
    return {
        "settings": _normalize_settings(source.get("settings", {})),
        "subscribers": _normalize_subscribers(source.get("subscribers", [])),
        "send_logs": _normalize_send_logs(source.get("send_logs", [])),
        "archives": _normalize_archives(source.get("archives", [])),
    }


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
        json.dumps(database.export_backup(jellyfin.JELLYFIN_CLIENT_VERSION), indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=jellynews-backup-v{APP_VERSION}-secrets.json"},
    )


@router.post("/settings/import")
async def import_settings(file: UploadFile = File(...)):
    try:
        payload = json.loads((await file.read()).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("le fichier doit contenir un objet JSON")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"JSON invalide : {exc}")
    backup_data = _prepare_backup_import(payload)
    result = database.import_backup_data(backup_data)
    scheduler.reschedule()
    return {"ok": True, **result}


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
    try:
        context, items = newsletter.build_context(settings)
        if not items:
            context, _ = newsletter.sample_context(settings, "Email de test JellyNews : rendu newsletter sans nouveauté détectée sur la période configurée.")
    except Exception:
        context, _ = newsletter.sample_context(settings, "Email de test JellyNews : rendu newsletter généré avec un échantillon, Jellyfin étant indisponible.")
    html = newsletter.render_html(settings, context, for_email=True, with_unsub=False)
    try:
        result = mailer.send_html(settings, [to], "JellyNews — Newsletter de test", html, newsletter._logo_path(settings))
    except Exception as exc:
        raise HTTPException(502, f"Échec SMTP : {exc}")
    if not result:
        raise HTTPException(502, "Le serveur SMTP a refusé le message")
    return {"ok": True}


@router.get("/preview", response_class=HTMLResponse)
def preview():
    """Rend la newsletter avec les vraies données Jellyfin ou un échantillon contrôlé."""
    settings = database.get_settings()
    try:
        context, items = newsletter.build_context(settings)
        if not items:
            context, _ = newsletter.sample_context(settings, "Prévisualisation : aucune nouveauté réelle détectée, rendu échantillon affiché.")
    except Exception:
        context, _ = newsletter.sample_context(settings, "Prévisualisation : Jellyfin indisponible, rendu échantillon affiché.")
    return HTMLResponse(newsletter.render_html(settings, context, for_email=False))


@router.post("/send-now")
def send_now(background_tasks: BackgroundTasks):
    if not newsletter.claim_campaign():
        raise HTTPException(409, "Une campagne newsletter est déjà en cours")
    background_tasks.add_task(newsletter.run_claimed, trigger="manual")
    return {"status": "queued", "queued": True}
