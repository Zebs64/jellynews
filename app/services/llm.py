"""Génération de l'introduction humoristique via une API compatible OpenAI
(OpenRouter, OpenAI, ou tout endpoint /chat/completions compatible)."""
import logging

import httpx

log = logging.getLogger("jellynews.llm")

FALLBACK_INTRO = (
    "Cette semaine, la médiathèque s'est encore agrandie ! "
    "Voici les nouveautés fraîchement ajoutées — installez-vous confortablement, "
    "le pop-corn n'est pas fourni mais l'enthousiasme, si."
)

SAMPLE_TITLES = ["Sharknado", "Le Fabuleux Destin d'Amélie Poulain", "Severance", "Daft Punk — Discovery"]


def request_intro(item_names: list[str], settings: dict) -> str:
    """Appelle le LLM et retourne l'intro. Lève une exception en cas d'échec
    (utilisé par le bouton « Tester » pour afficher l'erreur réelle)."""
    api_key = settings.get("llm_api_key")
    if not api_key:
        raise RuntimeError("Aucune clé API LLM configurée")

    base = (settings.get("llm_api_url") or "https://openrouter.ai/api/v1").rstrip("/")
    payload = {
        "model": settings.get("llm_model") or "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": settings.get("llm_prompt", "")},
            {
                "role": "user",
                "content": "Nouveautés de la semaine :\n- " + "\n- ".join(item_names[:40]),
            },
        ],
        "max_tokens": 400,
        "temperature": 0.9,
    }
    resp = httpx.post(
        f"{base}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    if not text:
        raise RuntimeError("Le modèle a renvoyé une réponse vide")
    return text


def generate_intro(item_names: list[str], settings: dict) -> str:
    """Version tolérante aux pannes pour l'envoi réel : l'échec du LLM ne doit
    JAMAIS bloquer la newsletter — on log et on retombe sur FALLBACK_INTRO."""
    if not settings.get("llm_api_key") or not item_names:
        return FALLBACK_INTRO
    try:
        return request_intro(item_names, settings)
    except Exception:
        log.exception("Échec de la génération LLM, utilisation du texte de repli")
        return FALLBACK_INTRO
