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
    "smtp_batch_size": "25",
    "smtp_batch_pause_seconds": "2",
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


# --------------------------------------------------------------- backups --
def _rows(conn: sqlite3.Connection, query: str) -> list[dict]:
    return [dict(r) for r in conn.execute(query).fetchall()]


def export_backup(app_version: str) -> dict:
    """Sauvegarde complète : config + abonnés + historique.

    Périmètre volontairement strict : pas d'utilisateurs, pas de secret.key,
    pas de fichiers uploadés. Les settings contiennent des secrets applicatifs,
    l'UI/API doivent donc continuer à avertir l'administrateur.
    """
    with get_conn() as conn:
        settings = dict(DEFAULTS)
        settings.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
        return {
            "schema_version": 2,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "app_version": app_version,
            "settings": settings,
            "subscribers": _rows(
                conn,
                "SELECT email, created_at FROM subscribers ORDER BY email",
            ),
            "send_logs": _rows(
                conn,
                "SELECT created_at, trigger, status, items_count, recipients, detail "
                "FROM send_logs ORDER BY id",
            ),
            "archives": _rows(
                conn,
                "SELECT created_at, subject, items_count, recipients, html "
                "FROM archives ORDER BY id",
            ),
        }


def _exists(conn: sqlite3.Connection, table: str, values: dict) -> bool:
    columns = list(values)
    where = " AND ".join(f"{col} = ?" for col in columns)
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",
        [values[col] for col in columns],
    ).fetchone()
    return row is not None


def import_backup_data(data: dict) -> dict:
    """Import fusionnel et idempotent d'une sauvegarde pré-validée.

    Les logs et archives n'ont pas de contrainte UNIQUE en base. On déduplique
    donc sur une clé métier déterministe : l'ensemble des colonnes exportées.
    """
    settings = {k: str(v) for k, v in data.get("settings", {}).items() if k in DEFAULTS}
    subscribers = data.get("subscribers", [])
    send_logs = data.get("send_logs", [])
    archives = data.get("archives", [])
    imported = {"settings": len(settings), "subscribers": 0, "send_logs": 0, "archives": 0}
    skipped = {"settings": 0, "subscribers": 0, "send_logs": 0, "archives": 0}

    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            list(settings.items()),
        )

        for sub in subscribers:
            row = conn.execute("SELECT 1 FROM subscribers WHERE email = ?", (sub["email"],)).fetchone()
            if row:
                skipped["subscribers"] += 1
                continue
            conn.execute(
                "INSERT INTO subscribers (email, created_at) VALUES (?, ?)",
                (sub["email"], sub["created_at"]),
            )
            imported["subscribers"] += 1

        for log in send_logs:
            key = {
                "created_at": log["created_at"],
                "trigger": log["trigger"],
                "status": log["status"],
                "items_count": log["items_count"],
                "recipients": log["recipients"],
                "detail": log["detail"],
            }
            if _exists(conn, "send_logs", key):
                skipped["send_logs"] += 1
                continue
            conn.execute(
                "INSERT INTO send_logs (created_at, trigger, status, items_count, recipients, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (log["created_at"], log["trigger"], log["status"], log["items_count"], log["recipients"], log["detail"]),
            )
            imported["send_logs"] += 1

        for archive in archives:
            base_key = {
                "created_at": archive["created_at"],
                "subject": archive["subject"],
                "items_count": archive["items_count"],
                "recipients": archive["recipients"],
            }
            html_candidates = dict.fromkeys([
                archive["html"],
                archive.get("_source_html", archive["html"]),
            ])
            if any(_exists(conn, "archives", {**base_key, "html": html_value}) for html_value in html_candidates):
                skipped["archives"] += 1
                continue
            conn.execute(
                "INSERT INTO archives (created_at, subject, items_count, recipients, html) "
                "VALUES (?, ?, ?, ?, ?)",
                (archive["created_at"], archive["subject"], archive["items_count"], archive["recipients"], archive["html"]),
            )
            imported["archives"] += 1

    return {"imported": imported, "skipped": skipped}


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
