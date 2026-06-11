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
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("jellynews.mailer")

LOGO_CID = "logo@jellynews"  # référencé dans le template : src="cid:logo@jellynews"
# Marqueur remplacé, PAR DESTINATAIRE, par son lien de désinscription signé.
UNSUB_PLACEHOLDER = "%%UNSUB_URL%%"


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
) -> int:
    """Envoie le HTML à chaque destinataire. Retourne le nombre d'envois réussis."""
    if not settings.get("smtp_host"):
        raise RuntimeError("Serveur SMTP non configuré")
    if not recipients:
        return 0

    sent = 0
    with _connect(settings) as server:
        for recipient in recipients:
            try:
                msg = _build_message(
                    settings, recipient, subject, html, logo_path,
                    inline_images, (unsub_urls or {}).get(recipient, ""),
                )
                server.send_message(msg)
                sent += 1
            except smtplib.SMTPException:
                log.exception("Échec d'envoi à %s", recipient)
    return sent
