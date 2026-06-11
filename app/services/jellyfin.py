"""Client API Jellyfin : ajouts récents (films, séries, épisodes, musique),
liste des bibliothèques et téléchargement des affiches."""
import datetime
import logging
import re

import httpx

log = logging.getLogger("jellynews.jellyfin")


def _get(settings: dict, path: str, params: dict | None = None) -> httpx.Response:
    base = settings["jellyfin_url"].rstrip("/")
    if not base or not settings.get("jellyfin_api_key"):
        raise RuntimeError("URL Jellyfin ou clé API non configurée")
    resp = httpx.get(
        f"{base}{path}",
        headers={"X-Emby-Token": settings["jellyfin_api_key"]},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp


def _parse_date(value: str | None) -> datetime.datetime | None:
    """Parse les dates Jellyfin (fractions de seconde à 7 chiffres, suffixe Z)."""
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    value = re.sub(r"\.(\d{6})\d+", r".\1", value)
    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def list_libraries(settings: dict) -> list[dict]:
    """Bibliothèques du serveur (pour les cases à cocher de l'admin)."""
    data = _get(settings, "/Library/MediaFolders").json()
    return [
        {"id": item["Id"], "name": item["Name"]}
        for item in data.get("Items", [])
        if item.get("CollectionType") != "boxsets"
    ]


def _server_id(settings: dict) -> str:
    """Id du serveur, nécessaire aux deep links /web/#/details. Non bloquant."""
    try:
        return _get(settings, "/System/Info").json().get("Id", "")
    except Exception:
        log.warning("Impossible de récupérer l'Id serveur (liens sans serverId)")
        return ""


def _query_items(settings: dict, parent_id: str | None = None) -> list[dict]:
    params = {
        "IncludeItemTypes": "Movie,Series,MusicAlbum,Episode",
        "Recursive": "true",
        "SortBy": "DateCreated",
        "SortOrder": "Descending",
        "Fields": "Overview,DateCreated,ProductionYear",
        "EnableImages": "true",
        "Limit": "500",
    }
    if parent_id:
        params["ParentId"] = parent_id
    return _get(settings, "/Items", params).json().get("Items", [])


def poster_url(settings: dict, item: dict, internal: bool = False, width: int = 400) -> str | None:
    """URL d'affiche : publique (email en mode lien / prévisualisation) ou
    interne (téléchargement pour incorporation)."""
    if not item.get("poster_path"):
        return None
    if internal:
        base = settings["jellyfin_url"].rstrip("/")
    else:
        base = (settings.get("jellyfin_external_url") or settings["jellyfin_url"]).rstrip("/")
    quality = 80 if internal else 90
    url = f"{base}{item['poster_path']}?maxWidth={width}&quality={quality}"
    if item.get("poster_tag"):
        url += f"&tag={item['poster_tag']}"
    return url


def download_poster(settings: dict, item: dict) -> tuple[bytes, str] | None:
    """Télécharge l'affiche via l'URL INTERNE (fonctionne même si Jellyfin
    n'est pas exposé publiquement). Retourne (octets, sous-type MIME)."""
    url = poster_url(settings, item, internal=True, width=220)
    if not url:
        return None
    try:
        resp = httpx.get(
            url, headers={"X-Emby-Token": settings["jellyfin_api_key"]}, timeout=30
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg")
        subtype = content_type.split("/")[-1].split(";")[0] or "jpeg"
        return resp.content, subtype
    except Exception:
        log.warning("Affiche introuvable pour %s", item.get("name"))
        return None


def fetch_recent_items(settings: dict) -> list[dict]:
    """Médias ajoutés durant les `lookback_days` derniers jours.

    - Les épisodes sont REGROUPÉS par série (« 8 nouveaux épisodes — saison 2 »).
    - Si `library_ids` est renseigné, seules ces bibliothèques sont interrogées.
    """
    lib_ids = [x.strip() for x in (settings.get("library_ids") or "").split(",") if x.strip()]
    raw: dict[str, dict] = {}
    if lib_ids:
        for lid in lib_ids:
            for item in _query_items(settings, lid):
                raw[item["Id"]] = item
    else:
        for item in _query_items(settings):
            raw[item["Id"]] = item

    lookback = int(settings.get("lookback_days", "7") or 7)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback)
    public_base = (settings.get("jellyfin_external_url") or settings["jellyfin_url"]).rstrip("/")
    server_id = _server_id(settings)

    def detail_url(item_id: str) -> str:
        url = f"{public_base}/web/#/details?id={item_id}"
        return url + (f"&serverId={server_id}" if server_id else "")

    items: list[dict] = []
    episodes: list[dict] = []
    for it in raw.values():
        created = _parse_date(it.get("DateCreated"))
        if not created or created < cutoff:
            continue
        if it.get("Type") == "Episode":
            episodes.append(it)
            continue
        tags = it.get("ImageTags") or {}
        items.append(
            {
                "id": it["Id"],
                "name": it.get("Name", "Sans titre"),
                "type": it.get("Type"),
                "year": it.get("ProductionYear"),
                "overview": (it.get("Overview") or "").strip(),
                "poster_path": f"/Items/{it['Id']}/Images/Primary" if tags.get("Primary") else None,
                "poster_tag": tags.get("Primary"),
                "url": detail_url(it["Id"]),
                "badge": "",
                "created": created,
            }
        )

    # ---- Regroupement des épisodes par série -------------------------------
    new_series_ids = {i["id"] for i in items if i["type"] == "Series"}
    groups: dict[str, dict] = {}
    for ep in episodes:
        sid = ep.get("SeriesId")
        if not sid:
            continue
        group = groups.setdefault(
            sid,
            {
                "name": ep.get("SeriesName", "Série"),
                "seasons": set(),
                "eps": [],
                "tag": ep.get("SeriesPrimaryImageTag"),
                "created": _parse_date(ep.get("DateCreated")) or cutoff,
            },
        )
        if ep.get("ParentIndexNumber") is not None:
            group["seasons"].add(ep["ParentIndexNumber"])
        group["eps"].append(ep)

    for sid, group in groups.items():
        count = len(group["eps"])
        badge = "1 nouvel épisode" if count == 1 else f"{count} nouveaux épisodes"
        seasons = sorted(group["seasons"])
        if seasons:
            label = "saison" if len(seasons) == 1 else "saisons"
            badge += f" — {label} {', '.join(str(s) for s in seasons)}"
        if sid in new_series_ids:
            # Série toute neuve : déjà une carte (avec son synopsis),
            # on lui ajoute simplement le badge du nombre d'épisodes.
            for existing in items:
                if existing["id"] == sid:
                    existing["badge"] = badge
            continue
        ep_list = ", ".join(
            f"S{ep.get('ParentIndexNumber', '?')}E{ep.get('IndexNumber', '?')} {ep.get('Name', '')}".strip()
            for ep in sorted(
                group["eps"],
                key=lambda e: (e.get("ParentIndexNumber") or 0, e.get("IndexNumber") or 0),
            )
        )
        items.append(
            {
                "id": sid,
                "name": group["name"],
                "type": "Series",
                "year": None,
                "overview": ep_list,
                "poster_path": f"/Items/{sid}/Images/Primary",
                "poster_tag": group["tag"],
                "url": detail_url(sid),
                "badge": badge,
                "created": group["created"],
            }
        )

    items.sort(key=lambda i: i["created"], reverse=True)
    for item in items:
        item["created"] = item["created"].isoformat()
    log.info("Jellyfin : %d nouveautés sur %d jours (%d groupes d'épisodes)",
             len(items), lookback, len(groups))
    return items


def test_connection(settings: dict) -> dict:
    """Vérifie la connexion et renvoie un petit échantillon pour l'UI."""
    items = fetch_recent_items(settings)
    return {
        "ok": True,
        "count": len(items),
        "sample": [i["name"] for i in items[:5]],
    }
