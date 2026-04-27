"""
Mod profile system — save/restore named loadouts (active mods + load order).
Stored per game in ~/.config/linux-mod-manager/profiles/<game_slug>.json
"""

import json
from pathlib import Path

PROFILES_DIR = Path.home() / ".config/linux-mod-manager/profiles"


def _path(game_slug: str) -> Path:
    return PROFILES_DIR / f"{game_slug}.json"


def load_all(game_slug: str) -> dict:
    """Returns {name: {active_mods: [...], load_order: [...]}}"""
    p = _path(game_slug)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _save_all(game_slug: str, profiles: dict) -> None:
    p = _path(game_slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profiles, indent=2))


def save(game_slug: str, name: str, active_mods: list[str], load_order: list[str],
         collection_mods: list[dict] | None = None,
         collection_game_domain: str | None = None) -> None:
    profiles = load_all(game_slug)
    entry = {"active_mods": active_mods, "load_order": load_order}
    if collection_mods is not None:
        entry["collection_mods"] = collection_mods
    if collection_game_domain is not None:
        entry["collection_game_domain"] = collection_game_domain
    profiles[name] = entry
    _save_all(game_slug, profiles)


def delete(game_slug: str, name: str) -> None:
    profiles = load_all(game_slug)
    if name in profiles:
        del profiles[name]
        _save_all(game_slug, profiles)


def get(game_slug: str, name: str) -> dict | None:
    return load_all(game_slug).get(name)


def get_collection_mods(game_slug: str, name: str) -> list[dict]:
    return load_all(game_slug).get(name, {}).get("collection_mods", [])
