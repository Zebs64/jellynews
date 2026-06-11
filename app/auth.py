"""Authentification : hachage bcrypt + session via cookie signé (itsdangerous).

SÉCURITÉ :
- Les mots de passe admin sont hachés avec bcrypt (jamais stockés en clair).
- La clé secrète de signature des sessions est générée au premier démarrage et
  persistée dans le volume /data : les sessions survivent aux redémarrages.
- Le cookie est HttpOnly + SameSite=Lax (protège des XSS et de la majorité des
  CSRF). Derrière un reverse-proxy HTTPS, passez COOKIE_SECURE=1 dans
  l'environnement pour ajouter le flag Secure.
"""
import os
import secrets

import bcrypt
from fastapi import HTTPException, Request
from itsdangerous import (
    BadSignature,
    SignatureExpired,
    URLSafeSerializer,
    URLSafeTimedSerializer,
)

from .database import DATA_DIR

SECRET_FILE = DATA_DIR / "secret.key"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 jours
COOKIE_NAME = "jellynews_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

_serializer: URLSafeTimedSerializer | None = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        if not SECRET_FILE.exists():
            SECRET_FILE.write_text(secrets.token_hex(32))
            SECRET_FILE.chmod(0o600)
        _serializer = URLSafeTimedSerializer(SECRET_FILE.read_text().strip())
    return _serializer


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_session_token(username: str) -> str:
    return _get_serializer().dumps({"u": username})


def get_session_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = _get_serializer().loads(token, max_age=SESSION_MAX_AGE)
        return data.get("u")
    except (BadSignature, SignatureExpired):
        return None


# ----------------------------------------------------- désinscription --
# Le lien de désinscription est un token signé contenant l'email : aucune
# colonne en base, impossible à forger sans la clé secrète, et sans
# expiration (un lien de désinscription doit rester valable indéfiniment).
def _unsub_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(SECRET_FILE.read_text().strip() if SECRET_FILE.exists()
                             else _bootstrap_secret(), salt="unsubscribe")


def _bootstrap_secret() -> str:
    _get_serializer()  # crée le fichier secret si besoin
    return SECRET_FILE.read_text().strip()


def make_unsubscribe_token(email: str) -> str:
    return _unsub_serializer().dumps(email)


def verify_unsubscribe_token(token: str) -> str | None:
    try:
        return _unsub_serializer().loads(token)
    except BadSignature:
        return None


def require_user(request: Request) -> str:
    """Dépendance FastAPI pour les routes API : 401 si non authentifié."""
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentification requise")
    return user
