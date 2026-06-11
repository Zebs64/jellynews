"""Couche de persistance SQLite : utilisateurs, configuration, abonnés, logs d'envoi."""
import datetime
import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "jellynews.db"

# Valeurs par défaut de toute la configuration. Sert aussi de liste blanche :
# l'API refuse d'écrire une clé absente d'ici.
DEFAULTS = {
    "jellyfin_url": "",
    "jellyfin_api_key": "",
    # URL publique du serveur Jellyfin, utilisée pour les posters dans l'email.
    # Si vide, on retombe sur jellyfin_url (qui doit alors être joignable
    # depuis l'extérieur, sinon les images seront cassées chez les abonnés).
    "jellyfin_external_url": "",
    "lookback_days": "7",
    # embed = posters téléchargés et incorporés à l'email (pas besoin de
    # Jellyfin public) ; link = simples URLs vers jellyfin_external_url.
    "poster_mode": "embed",
    # IDs de bibliothèques Jellyfin à inclure, séparés par des virgules.
    # Vide = toutes les bibliothèques.
    "library_ids": "",
    # URL publique de JellyNews lui-même : sert à construire les liens de
    # désinscription dans les emails. Vide = pas de lien de désinscription.
    "app_public_url": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_security": "starttls",  # starttls | ssl | none
    "smtp_user": "",
    "smtp_password": "",
    "smtp_sender": "",
    "llm_api_url": "https://openrouter.ai/api/v1",
    "llm_api_key": "",
    "llm_model": "openai/gpt-4o-mini",
    "llm_prompt": (
        "Tu es le rédacteur plein d'humour de la newsletter d'un serveur multimédia "
        "Jellyfin familial. À partir de la liste des nouveautés de la semaine, écris "
        "une courte note d'introduction (3 à 5 phrases) drôle et chaleureuse en "
        "français, qui taquine gentiment les titres ajoutés. Pas de liste, pas de "
        "markdown, uniquement un paragraphe de texte."
    ),
    # Fuseau horaire du cron d'envoi (la variable d'env TZ sert de défaut).
    "timezone": os.environ.get("TZ", "Europe/Paris"),
    # Derrière un reverse-proxy : utiliser X-Forwarded-For pour identifier le
    # client (rate-limiting du login). trusted_proxies (IPs/CIDR, séparés par
    # des virgules) limite la confiance à ces pairs ; vide = pair direct
    # quelconque (suffisant si seul le proxy peut joindre le conteneur).
    "behind_proxy": "0",
    "trusted_proxies": "",
    # Flag Secure sur le cookie de session (à activer derrière HTTPS).
    "cookie_secure": "0",
    "schedule_enabled": "0",
    "schedule_day": "4",      # 0 = lundi ... 6 = dimanche
    "schedule_hour": "18",
    "schedule_minute": "0",
    "discord_webhook_url": "",
    "newsletter_title": "JellyNews — Les nouveautés de votre médiathèque",
    "logo_filename": "",
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                subject TEXT NOT NULL,
                items_count INTEGER NOT NULL DEFAULT 0,
                recipients INTEGER NOT NULL DEFAULT 0,
                html TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS send_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                items_count INTEGER NOT NULL DEFAULT 0,
                recipients INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT ''
            );
            """
        )


# ---------------------------------------------------------------- settings --
def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULTS)
    settings.update({r["key"]: r["value"] for r in rows})
    return settings


def set_settings(values: dict) -> None:
    clean = {k: str(v) for k, v in values.items() if k in DEFAULTS}
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            list(clean.items()),
        )


# ------------------------------------------------------------------- users --
def has_admin() -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def create_admin(username: str, password_hash: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )


def get_user(username: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


# -------------------------------------------------------------- subscribers --
def list_subscribers() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, created_at FROM subscribers ORDER BY email"
        ).fetchall()
    return [dict(r) for r in rows]


def add_subscriber(email: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscribers (email, created_at) VALUES (?, ?)",
            (email, datetime.datetime.now().isoformat(timespec="seconds")),
        )


def delete_subscriber(sub_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM subscribers WHERE id = ?", (sub_id,))


def delete_subscriber_by_email(email: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM subscribers WHERE email = ?", (email,))
        return cur.rowcount > 0


# ---------------------------------------------------------------- archives --
def add_archive(subject: str, items_count: int, recipients: int, html: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO archives (created_at, subject, items_count, recipients, html) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.datetime.now().isoformat(timespec="seconds"),
                subject,
                items_count,
                recipients,
                html,
            ),
        )


def list_archives(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, subject, items_count, recipients "
            "FROM archives ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_archive(archive_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM archives WHERE id = ?", (archive_id,)
        ).fetchone()


# -------------------------------------------------------------------- logs --
def add_log(trigger: str, status: str, items_count: int, recipients: int, detail: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO send_logs (created_at, trigger, status, items_count, recipients, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.datetime.now().isoformat(timespec="seconds"),
                trigger,
                status,
                items_count,
                recipients,
                detail[:2000],
            ),
        )


def list_logs(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM send_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
