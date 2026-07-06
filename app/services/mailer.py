"""Envoi SMTP de la newsletter HTML, avec logo et affiches embarqués en
pièces jointes inline.

COMPATIBILITÉ EMAIL : les images sont attachées en `Content-ID` (cid:) plutôt
qu'en base64 dans le HTML — les images base64 sont bloquées par Gmail/Outlook,
alors que les pièces jointes inline sont affichées partout.

CONFIDENTIALITÉ : un message distinct est envoyé à chaque abonné (pas de
liste en clair dans le champ To/Cc), ce qui permet aussi d'injecter un lien
de désinscription propre à chaque destinataire.
"""
import logging
import mimetypes
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("jellynews.mailer")

LOGO_CID = "logo@jellynews"  # référencé dans le template : src="cid:logo@jellynews"
# Marqueur remplacé, PAR DESTINATAIRE, par son lien de désinscription signé.
UNSUB_PLACEHOLDER = "%%UNSUB_URL%%"
SMTP_BATCH_SIZE_MIN = 1
SMTP_BATCH_SIZE_MAX = 500
SMTP_BATCH_PAUSE_MIN = 0
SMTP_BATCH_PAUSE_MAX = 3600


@dataclass(frozen=True)
class SendResult:
    total: int
    sent: int
    failures: list[str]

    @property
    def failed(self) -> int:
        return len(self.failures)

    def __bool__(self) -> bool:
        return self.sent > 0


def _int_setting(settings: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(settings.get(key, default)))
    except (TypeError, ValueError):
        raise ValueError(f"{key} doit être un entier")
    if value < minimum or value > maximum:
        raise ValueError(f"{key} doit être compris entre {minimum} et {maximum}")
    return value


def throttle_settings(settings: dict) -> tuple[int, int]:
    return (
        _int_setting(settings, "smtp_batch_size", 25, SMTP_BATCH_SIZE_MIN, SMTP_BATCH_SIZE_MAX),
        _int_setting(settings, "smtp_batch_pause_seconds", 2, SMTP_BATCH_PAUSE_MIN, SMTP_BATCH_PAUSE_MAX),
    )


def _masked_recipient(email: str) -> str:
    local, sep, domain = email.partition("@")
    if not sep:
        return "destinataire invalide"
    head = local[:1] or "?"
    return f"{head}***@{domain}"


def _build_message(
    settings: dict,
    recipient: str,
    subject: str,
    html: str,
    logo_path: Path | None,
    inline_images: dict[str, tuple[bytes, str]] | None = None,
    unsub_url: str = "",
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.get("smtp_sender") or settings.get("smtp_user", "")
    msg["To"] = recipient
    if unsub_url:
        # Désinscription en un clic gérée nativement par Gmail/Outlook (RFC 8058).
        msg["List-Unsubscribe"] = f"<{unsub_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    # Version texte de repli pour les clients sans HTML (et meilleur score spam).
    text = "Votre client mail ne supporte pas le HTML. Consultez les nouveautés sur votre serveur Jellyfin."
    if unsub_url:
        text += f"\nSe désinscrire : {unsub_url}"
    msg.set_content(text)
    msg.add_alternative(html.replace(UNSUB_PLACEHOLDER, unsub_url), subtype="html")

    related = msg.get_payload()[1]  # la partie HTML devient multipart/related
    if logo_path and logo_path.exists():
        ctype, _ = mimetypes.guess_type(logo_path.name)
        maintype, subtype = (ctype or "image/png").split("/", 1)
        related.add_related(
            logo_path.read_bytes(), maintype=maintype, subtype=subtype, cid=f"<{LOGO_CID}>"
        )
    for cid, (data, subtype) in (inline_images or {}).items():
        related.add_related(data, maintype="image", subtype=subtype, cid=f"<{cid}>")
    return msg


def _connect(settings: dict) -> smtplib.SMTP:
    host = settings["smtp_host"]
    port = int(settings.get("smtp_port") or 587)
    security = settings.get("smtp_security", "starttls")
    context = ssl.create_default_context()
    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if security == "starttls":
            server.starttls(context=context)
    if settings.get("smtp_user"):
        server.login(settings["smtp_user"], settings.get("smtp_password", ""))
    return server


def send_html(
    settings: dict,
    recipients: list[str],
    subject: str,
    html: str,
    logo_path: Path | None = None,
    inline_images: dict[str, tuple[bytes, str]] | None = None,
    unsub_urls: dict[str, str] | None = None,
) -> SendResult:
    """Envoie le HTML à chaque destinataire, avec To unique et throttling par vagues."""
    if not settings.get("smtp_host"):
        raise RuntimeError("Serveur SMTP non configuré")
    if not recipients:
        return SendResult(total=0, sent=0, failures=[])

    batch_size, pause_seconds = throttle_settings(settings)
    sent = 0
    failures: list[str] = []
    with _connect(settings) as server:
        total = len(recipients)
        for index, recipient in enumerate(recipients, start=1):
            try:
                msg = _build_message(
                    settings, recipient, subject, html, logo_path,
                    inline_images, (unsub_urls or {}).get(recipient, ""),
                )
                server.send_message(msg)
                sent += 1
            except (smtplib.SMTPException, OSError) as exc:
                log.exception("Échec d'envoi à %s", _masked_recipient(recipient))
                failures.append(f"{_masked_recipient(recipient)}: {type(exc).__name__}")
            if index < total and index % batch_size == 0 and pause_seconds:
                log.info("Pause SMTP %ss après %s/%s destinataires", pause_seconds, index, total)
                time.sleep(pause_seconds)
    return SendResult(total=len(recipients), sent=sent, failures=failures)
