"""Sanitizer partagé pour les diagnostics et logs SMTP persistés/exportés."""
import html
import re

SMTP_TEXT_MAX = 500

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|smtp_password|token|secret|api[_-]?key)\b\s*[:=]\s*"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s;,'\"]+)"
)
_HTML_TAG_RE = re.compile(r"<[^>]*>")


def mask_email(email: str) -> str:
    local, sep, domain = email.partition("@")
    if not sep:
        return "destinataire invalide"
    head = local[:1] or "?"
    return f"{head}***@{domain}"


def clean_smtp_text(value: object, limit: int = SMTP_TEXT_MAX) -> str:
    """Retourne un texte borné sans PII email, secrets, HTML brut ni CR/LF."""
    if value is None:
        text = ""
    elif isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)

    text = html.unescape(text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = "".join(ch if ch.isprintable() or ch.isspace() else " " for ch in text)
    text = _HTML_TAG_RE.sub("[html]", text)
    text = _EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
