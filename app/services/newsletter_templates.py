"""Registre contrôlé des templates newsletter et normalisation des blocs v1.1.0."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DEFAULT_TEMPLATE_ID = "classic"
DEFAULT_BLOCK_ORDER = ["preheader", "header", "intro", "media_sections", "footer"]
MANDATORY_BLOCK_IDS = {"preheader", "header", "media_sections", "footer"}
OPTIONAL_BLOCK_IDS = {"intro"}
KNOWN_BLOCK_IDS = set(DEFAULT_BLOCK_ORDER)


@dataclass(frozen=True)
class NewsletterTemplate:
    id: str
    name: str
    template_file: str
    description: str
    badge: str = ""


TEMPLATES: dict[str, NewsletterTemplate] = {
    "classic": NewsletterTemplate(
        id="classic",
        name="Classique",
        template_file="newsletter.html",
        description="Rendu historique JellyNews, sobre et compatible par défaut.",
        badge="Défaut",
    ),
    "editorial": NewsletterTemplate(
        id="editorial",
        name="Courant éditorial",
        template_file="newsletter_editorial.html",
        description="Hiérarchie magazine : premier média mis en avant, lignes sobres ensuite.",
    ),
    "compact": NewsletterTemplate(
        id="compact",
        name="Catalogue compact",
        template_file="newsletter_compact.html",
        description="Version dense pour semaines chargées, posters réduits et lecture rapide.",
        badge="Volume élevé",
    ),
    "showcase": NewsletterTemplate(
        id="showcase",
        name="Affiche de séance",
        template_file="newsletter_showcase.html",
        description="Rendu plus scénique pour une programmation courte ou moyenne.",
    ),
}

BLOCK_LABELS = {
    "preheader": "Préheader invisible",
    "header": "En-tête",
    "intro": "Introduction IA",
    "media_sections": "Sections médias",
    "footer": "Pied de page",
}


def template_options() -> list[dict[str, Any]]:
    return [
        {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "badge": template.badge,
            "default": template.id == DEFAULT_TEMPLATE_ID,
        }
        for template in TEMPLATES.values()
    ]


def block_options() -> list[dict[str, Any]]:
    return [
        {
            "id": block_id,
            "label": BLOCK_LABELS[block_id],
            "mandatory": block_id in MANDATORY_BLOCK_IDS,
            "enabled": True,
        }
        for block_id in DEFAULT_BLOCK_ORDER
    ]


def validate_template_id(value: Any) -> str:
    template_id = str(value or DEFAULT_TEMPLATE_ID).strip() or DEFAULT_TEMPLATE_ID
    if template_id not in TEMPLATES:
        raise ValueError(f"Template newsletter inconnu : {template_id}")
    return template_id


def default_blocks() -> list[dict[str, Any]]:
    return [
        {
            "id": block_id,
            "enabled": True,
            "mandatory": block_id in MANDATORY_BLOCK_IDS,
            "label": BLOCK_LABELS[block_id],
        }
        for block_id in DEFAULT_BLOCK_ORDER
    ]


def _coerce_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Champ booléen invalide : {field}")


def _parse_blocks_payload(value: Any) -> list[Any]:
    if value in (None, ""):
        return default_blocks()
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Configuration des blocs invalide : {exc.msg}") from exc
    if isinstance(payload, dict):
        payload = payload.get("blocks")
    if not isinstance(payload, list):
        raise ValueError("La configuration des blocs newsletter doit être une liste")
    return payload


def normalize_blocks(value: Any) -> list[dict[str, Any]]:
    payload = _parse_blocks_payload(value)
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(payload):
        if isinstance(raw, str):
            block_id = raw
            enabled = True
        elif isinstance(raw, dict):
            block_id = str(raw.get("id") or "").strip()
            enabled = _coerce_bool(raw.get("enabled", True), field=f"blocks[{index}].enabled")
        else:
            raise ValueError(f"Bloc newsletter invalide à l'index {index}")
        if block_id not in KNOWN_BLOCK_IDS:
            raise ValueError(f"Bloc newsletter inconnu : {block_id}")
        if block_id in seen:
            raise ValueError(f"Bloc newsletter dupliqué : {block_id}")
        if block_id in MANDATORY_BLOCK_IDS and not enabled:
            raise ValueError(f"Bloc newsletter obligatoire désactivé : {block_id}")
        seen.add(block_id)
        normalized.append({
            "id": block_id,
            "enabled": enabled,
            "mandatory": block_id in MANDATORY_BLOCK_IDS,
            "label": BLOCK_LABELS[block_id],
        })

    missing = MANDATORY_BLOCK_IDS - seen
    if missing:
        raise ValueError("Bloc(s) newsletter obligatoire(s) manquant(s) : " + ", ".join(sorted(missing)))

    # Ordre contrôlé : preheader toujours premier, footer toujours dernier.
    by_id = {block["id"]: block for block in normalized}
    middle = [
        block for block in normalized
        if block["id"] not in {"preheader", "footer"}
    ]
    return [by_id["preheader"], *middle, by_id["footer"]]


def serialize_blocks(blocks: list[dict[str, Any]]) -> str:
    return json.dumps(
        [{"id": block["id"], "enabled": bool(block["enabled"])} for block in blocks],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalize_settings(settings: dict[str, Any]) -> dict[str, str]:
    template_id = validate_template_id(settings.get("newsletter_template_id", DEFAULT_TEMPLATE_ID))
    blocks = normalize_blocks(settings.get("newsletter_blocks_json"))
    return {
        "newsletter_template_id": template_id,
        "newsletter_blocks_json": serialize_blocks(blocks),
    }


def resolve(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_settings(settings)
    template = TEMPLATES[normalized["newsletter_template_id"]]
    blocks = normalize_blocks(normalized["newsletter_blocks_json"])
    return {
        "template": template,
        "blocks": blocks,
        "body_blocks": [block for block in blocks if block["id"] not in {"preheader", "footer"}],
        "block_map": {block["id"]: block for block in blocks},
        "settings": normalized,
    }
