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
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from ..smtp_sanitizer import SMTP_TEXT_MAX, clean_smtp_text, mask_email

log = logging.getLogger("jellynews.mailer")

LOGO_CID = "logo@jellynews"  # référencé dans le template : src="cid:logo@jellynews"
# Marqueur remplacé, PAR DESTINATAIRE, par son lien de désinscription signé.
UNSUB_PLACEHOLDER = "%%UNSUB_URL%%"
SMTP_BATCH_SIZE_MIN = 1
SMTP_BATCH_SIZE_MAX = 500
SMTP_BATCH_PAUSE_MIN = 0
SMTP_BATCH_PAUSE_MAX = 3600
SMTP_DIAGNOSTIC_TEXT_MAX = SMTP_TEXT_MAX

_ENHANCED_STATUS_RE = re.compile(r"\b([245]\.\d\.\d)\b")

_SMTP_HINTS: dict[tuple[int | None, str | None], tuple[str, str, bool | None]] = {
    (550, "5.7.1"): (
        "rejet_policy_spam",
        "Rejet anti-spam, politique serveur ou réputation expéditeur. Vérifier SPF/DKIM/DMARC, réputation IP/domaine et contenu.",
        False,
    ),
    (554, "5.7.1"): (
        "contenu_policy_refuse",
        "Contenu refusé, réputation ou règle de politique. Vérifier contenu, liens, réputation et authentification domaine.",
        False,
    ),
    (552, "5.3.4"): (
        "message_trop_gros",
        "Message trop volumineux. Réduire images intégrées, nombre de médias ou poids HTML.",
        False,
    ),
    (451, "4.7.0"): (
        "rate_limit_greylisting",
        "Limite temporaire, greylisting ou ralentissement requis. Augmenter la pause entre vagues SMTP.",
        True,
    ),
    (421, None): (
        "service_temporaire_throttle",
        "Service indisponible, quota ou throttling temporaire. Réessayer plus tard et réduire le débit.",
        True,
    ),
}


@dataclass(frozen=True)
class SendResult:
    total: int
    sent: int
    failures: list[str]
    failure_details: list[dict] = field(default_factory=list)

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
    return mask_email(email)


def _clean_smtp_text(value: object, limit: int = SMTP_DIAGNOSTIC_TEXT_MAX) -> str:
    return clean_smtp_text(value, limit)


def _smtp_code(value: object) -> int | None:
    try:
        code = int(str(value))
    except (TypeError, ValueError):
        return None
    return code if 100 <= code <= 999 else None


def _first_recipient_refusal(exc: smtplib.SMTPRecipientsRefused) -> tuple[int | None, object]:
    for refusal in exc.recipients.values():
        if isinstance(refusal, tuple) and len(refusal) >= 2:
            return _smtp_code(refusal[0]), refusal[1]
    return None, ""


def _extract_smtp_response(exc: BaseException) -> tuple[int | None, str]:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        code, raw_error = _first_recipient_refusal(exc)
        return code, _clean_smtp_text(raw_error)
    code = _smtp_code(getattr(exc, "smtp_code", None))
    raw_error = getattr(exc, "smtp_error", "")
    return code, _clean_smtp_text(raw_error)


def _classify_smtp(exc: BaseException, smtp_code: int | None, smtp_error: str) -> tuple[str, str, bool | None]:
    enhanced = None
    match = _ENHANCED_STATUS_RE.search(smtp_error)
    if match:
        enhanced = match.group(1)
    if (smtp_code, enhanced) in _SMTP_HINTS:
        return _SMTP_HINTS[(smtp_code, enhanced)]
    if (smtp_code, None) in _SMTP_HINTS:
        return _SMTP_HINTS[(smtp_code, None)]
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "smtp_auth", "Authentification SMTP refusée. Vérifier identifiant, mot de passe et politique du fournisseur.", False
    if smtp_code is not None:
        if 400 <= smtp_code < 500:
            return (
                "smtp_temporaire",
                "Erreur temporaire SMTP, potentiellement réessayable après délai.",
                True,
            )
        if 500 <= smtp_code < 600:
            return (
                "smtp_permanent",
                "Erreur SMTP permanente ou politique serveur. Corriger configuration, destinataire, contenu ou réputation avant nouvel essai.",
                False,
            )
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "smtp_disconnected", "Connexion SMTP interrompue. Réessayer plus tard et vérifier stabilité réseau/serveur.", True
    if isinstance(exc, smtplib.SMTPException):
        return "smtp_unknown", "Erreur SMTP non catégorisée. Consulter le message et les journaux du fournisseur.", None
    if isinstance(exc, (TimeoutError, ConnectionError, ssl.SSLError)):
        return "network_error", "Erreur réseau ou TLS pendant l'échange SMTP. Vérifier connectivité, port, TLS et disponibilité du serveur.", True
    if isinstance(exc, OSError):
        return "network_error", "Erreur système ou réseau pendant l'envoi SMTP. Vérifier connectivité, DNS, port et pare-feu.", True
    return "smtp_unknown", "Erreur SMTP non catégorisée. Consulter le message et les journaux du fournisseur.", None


def smtp_diagnostic(exc: BaseException) -> dict:
    """Diagnostic SMTP pur, borné et sans PII brute exploitable côté admin."""
    smtp_code, smtp_error = _extract_smtp_response(exc)
    category, hint, retryable = _classify_smtp(exc, smtp_code, smtp_error)
    return {
        "error_class": type(exc).__name__,
        "smtp_code": smtp_code,
        "smtp_error": smtp_error,
        "smtp_category": category,
        "smtp_hint": _clean_smtp_text(hint),
        "retryable": retryable,
    }


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
    failure_details: list[dict] = []
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
                masked = _masked_recipient(recipient)
                log.exception("Échec d'envoi à %s", masked)
                failures.append(f"{masked}: {type(exc).__name__}")
                failure_details.append({"recipient": masked, **smtp_diagnostic(exc)})
            if index < total and index % batch_size == 0 and pause_seconds:
                log.info("Pause SMTP %ss après %s/%s destinataires", pause_seconds, index, total)
                time.sleep(pause_seconds)
    return SendResult(total=len(recipients), sent=sent, failures=failures, failure_details=failure_details)
