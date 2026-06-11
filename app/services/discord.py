"""Publication d'un résumé de la newsletter sur Discord via webhook (optionnel)."""
import logging

import httpx

log = logging.getLogger("jellynews.discord")

TYPE_LABELS = {"Movie": "🎬 Films", "Series": "📺 Séries", "MusicAlbum": "🎵 Musique"}


def send_summary(settings: dict, items: list[dict], intro: str) -> bool:
    """Envoie un embed récapitulatif. Retourne False si aucun webhook configuré."""
    url = (settings.get("discord_webhook_url") or "").strip()
    if not url:
        return False

    fields = []
    for media_type, label in TYPE_LABELS.items():
        names = [i["name"] for i in items if i["type"] == media_type]
        if not names:
            continue
        # Limite Discord : 1024 caractères par field.
        value = "\n".join(f"• {n}" for n in names)
        if len(value) > 1000:
            value = value[:1000] + "\n…"
        fields.append({"name": f"{label} ({len(names)})", "value": value, "inline": False})

    payload = {
        "username": "JellyNews",
        "embeds": [
            {
                "title": settings.get("newsletter_title", "JellyNews"),
                # Limite Discord : 4096 caractères pour la description.
                "description": intro[:4000],
                "color": 0x5AA9FF,
                "fields": fields,
            }
        ],
    }
    resp = httpx.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    log.info("Résumé publié sur Discord (%d catégories)", len(fields))
    return True
