"""Validation et garde-fous pour les URLs publiques rendues par JellyNews."""
from urllib.parse import urlsplit

ALLOWED_PUBLIC_URL_SCHEMES = {"http", "https"}


def is_public_http_url(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlsplit(text)
    return parsed.scheme.lower() in ALLOWED_PUBLIC_URL_SCHEMES and bool(parsed.netloc)


def normalize_public_http_url(value: object, *, field: str, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text and allow_empty:
        return ""
    if not is_public_http_url(text):
        raise ValueError(f"URL invalide pour {field} : seuls http:// et https:// avec hôte sont acceptés")
    return text


def safe_public_href(value: object, *, fallback: str = "#") -> str:
    text = str(value or "").strip()
    return text if is_public_http_url(text) else fallback
