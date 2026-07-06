"""Orchestrateur : Jellyfin -> LLM -> rendu HTML -> SMTP -> Discord -> archive/log."""
import datetime
import logging
import threading
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import auth, database
from . import discord, jellyfin, llm, mailer

log = logging.getLogger("jellynews.newsletter")


class CampaignAlreadyRunning(RuntimeError):
    """Une campagne newsletter est déjà active dans ce processus."""


_campaign_lock = threading.Lock()

EMAIL_TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "email"
_env = Environment(
    loader=FileSystemLoader(EMAIL_TEMPLATES),
    autoescape=select_autoescape(["html"]),
)

SECTION_ORDER = [
    ("Movie", "🎬 Films"),
    ("Series", "📺 Séries"),
    ("MusicAlbum", "🎵 Musique"),
]

# Garde-fou sur le poids de l'email : au-delà, les affiches restantes
# retombent en simples liens (un email > ~5 Mo finit souvent en spam).
MAX_EMBEDDED_POSTERS = 50


def claim_campaign() -> bool:
    return _campaign_lock.acquire(blocking=False)


def run_claimed(trigger: str = "manual") -> dict | None:
    try:
        return run(trigger=trigger, _lock_already_acquired=True)
    except Exception:
        log.exception("Campagne newsletter %s échouée", trigger)
        return None
    finally:
        _campaign_lock.release()


def _logo_path(settings: dict) -> Path | None:
    filename = settings.get("logo_filename")
    if filename:
        path = database.UPLOADS_DIR / filename
        if path.exists():
            return path
    return None


def _truncate(text: str, length: int = 320) -> str:
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "…"


def build_context(settings: dict) -> tuple[dict, list[dict]]:
    """Interroge Jellyfin + LLM et construit le contexte du template."""
    items = jellyfin.fetch_recent_items(settings)

    sections = []
    for media_type, label in SECTION_ORDER:
        typed = [i for i in items if i["type"] == media_type]
        if typed:
            for item in typed:
                item["overview"] = _truncate(item["overview"]) or "Pas de synopsis disponible."
            # Clé "entries" (et non "items") : en Jinja2, section.items
            # résoudrait la méthode dict.items() au lieu de la liste.
            sections.append({"label": label, "entries": typed})

    intro = llm.generate_intro([i["name"] for i in items], settings) if items else ""
    today = datetime.date.today()
    lookback = int(settings.get("lookback_days", "7") or 7)
    start = today - datetime.timedelta(days=lookback)

    context = {
        "title": settings.get("newsletter_title", "JellyNews"),
        "intro": intro,
        "sections": sections,
        "period_label": f"Nouveautés du {start.strftime('%d/%m/%Y')} au {today.strftime('%d/%m/%Y')}",
        "preheader": f"{len(items)} nouveautés cette semaine sur votre serveur Jellyfin",
        "now_year": today.year,
    }
    return context, items


def download_posters(settings: dict, context: dict) -> dict[str, tuple[bytes, str]]:
    """Télécharge les affiches (via l'URL interne) pour incorporation cid:.
    Marque chaque entrée avec son cid ; les échecs retombent en lien distant."""
    inline: dict[str, tuple[bytes, str]] = {}
    for section in context["sections"]:
        for item in section["entries"]:
            if len(inline) >= MAX_EMBEDDED_POSTERS:
                log.warning("Plus de %d affiches : les suivantes restent en lien",
                            MAX_EMBEDDED_POSTERS)
                return inline
            downloaded = jellyfin.download_poster(settings, item)
            if downloaded:
                cid = f"poster-{item['id']}@jellynews"
                inline[cid] = downloaded
                item["poster_cid"] = cid
    return inline


def render_html(settings: dict, context: dict, for_email: bool = True,
                with_unsub: bool = False) -> str:
    """Rend le template.

    - Email : logo et affiches en cid: (si mode embed), lien de désinscription
      sous forme de marqueur remplacé par destinataire dans le mailer.
    - Prévisualisation / archive : URLs web classiques, pas de désinscription.
    """
    embed = settings.get("poster_mode", "embed") == "embed"
    for section in context["sections"]:
        for item in section["entries"]:
            if for_email and embed and item.get("poster_cid"):
                item["poster_src"] = f"cid:{item['poster_cid']}"
            else:
                item["poster_src"] = jellyfin.poster_url(settings, item)

    logo = _logo_path(settings)
    logo_src = None
    if logo:
        logo_src = f"cid:{mailer.LOGO_CID}" if for_email else f"/uploads/{logo.name}"

    unsubscribe_url = mailer.UNSUB_PLACEHOLDER if (for_email and with_unsub) else None
    template = _env.get_template("newsletter.html")
    return template.render(**context, logo_src=logo_src, unsubscribe_url=unsubscribe_url)


def run(trigger: str = "manual", *, _lock_already_acquired: bool = False) -> dict:
    """Pipeline complet d'envoi. Toujours journalisé dans send_logs."""
    if not _lock_already_acquired and not claim_campaign():
        database.add_log(trigger, "skipped", 0, 0, "Campagne déjà en cours")
        raise CampaignAlreadyRunning("Une campagne newsletter est déjà en cours")
    try:
        return _run(trigger)
    finally:
        if not _lock_already_acquired:
            _campaign_lock.release()


def _run(trigger: str) -> dict:
    """Implémentation du pipeline, appelée après acquisition du verrou."""
    settings = database.get_settings()
    try:
        context, items = build_context(settings)
    except Exception as exc:
        log.exception("Échec de la récupération Jellyfin")
        database.add_log(trigger, "error", 0, 0, f"Jellyfin : {exc}")
        raise

    if not items:
        database.add_log(trigger, "skipped", 0, 0, "Aucune nouveauté sur la période")
        return {"status": "skipped", "items": 0, "sent": 0}

    inline_images: dict[str, tuple[bytes, str]] = {}
    if settings.get("poster_mode", "embed") == "embed":
        inline_images = download_posters(settings, context)

    app_url = (settings.get("app_public_url") or "").rstrip("/")
    subscribers = [s["email"] for s in database.list_subscribers()]
    unsub_urls = {
        email: f"{app_url}/unsubscribe/{auth.make_unsubscribe_token(email)}"
        for email in subscribers
    } if app_url else {}

    html = render_html(settings, context, for_email=True, with_unsub=bool(app_url))
    subject = f"{context['title']} — {datetime.date.today().strftime('%d/%m/%Y')}"

    errors = []
    send_result = mailer.SendResult(total=len(subscribers), sent=0, failures=[])
    try:
        send_result = mailer.send_html(
            settings, subscribers, subject, html,
            _logo_path(settings), inline_images, unsub_urls,
        )
        if send_result.failures:
            errors.append(f"SMTP partiel : {send_result.failed} échec(s) ({'; '.join(send_result.failures[:5])})")
    except Exception as exc:
        log.exception("Échec de l'envoi SMTP")
        errors.append(f"SMTP : {exc}")

    try:
        discord.send_summary(settings, items, context["intro"])
    except Exception as exc:
        log.exception("Échec du webhook Discord")
        errors.append(f"Discord : {exc}")

    # Archive : version navigateur (images distantes, sans désinscription).
    try:
        database.add_archive(
            subject, len(items), send_result.sent,
            render_html(settings, context, for_email=False),
        )
    except Exception as exc:
        log.exception("Échec de l'archivage")
        errors.append(f"Archive : {exc}")

    status = "ok" if not errors else ("partial" if send_result.sent else "error")
    detail = f"{send_result.sent}/{len(subscribers)} emails envoyés. " + " | ".join(errors)
    database.add_log(trigger, status, len(items), send_result.sent, detail.strip())
    return {"status": status, "items": len(items), "sent": send_result.sent, "errors": errors}
