"""
Mod profile system — save/restore named loadouts (active mods + load order).
Stored per game in ~/.config/linux-mod-manager/profiles/<game_slug>.json

Active profile tracked via reserved "_active" key in the same file.
"""

import json
from pathlib import Path

PROFILES_DIR = Path.home() / ".config/linux-mod-manager/profiles"

_ACTIVE_KEY = "_active"
SYSTEM_PROFILES = ("Vanilla", "All Mods")


def _path(game_slug: str) -> Path:
    return PROFILES_DIR / f"{game_slug}.json"


def _load_raw(game_slug: str) -> dict:
    p = _path(game_slug)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _save_raw(game_slug: str, data: dict) -> None:
    p = _path(game_slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def load_all(game_slug: str) -> dict:
    """Returns {name: {active_mods: [...], load_order: [...]}} — excludes internal keys."""
    raw = _load_raw(game_slug)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _save_all(game_slug: str, profiles: dict) -> None:
    raw = _load_raw(game_slug)
    new_raw = {k: v for k, v in raw.items() if k.startswith("_")}
    new_raw.update(profiles)
    _save_raw(game_slug, new_raw)


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
    if name in SYSTEM_PROFILES:
        raise ValueError(f"Cannot delete system profile: {name}")
    profiles = load_all(game_slug)
    if name in profiles:
        del profiles[name]
        _save_all(game_slug, profiles)


def get(game_slug: str, name: str) -> dict | None:
    return load_all(game_slug).get(name)


# ── Active profile tracking ───────────────────────────────────────────────────

def set_active(game_slug: str, name: str | None) -> None:
    raw = _load_raw(game_slug)
    if name is None:
        raw.pop(_ACTIVE_KEY, None)
    else:
        raw[_ACTIVE_KEY] = name
    _save_raw(game_slug, raw)


def get_active(game_slug: str) -> str | None:
    return _load_raw(game_slug).get(_ACTIVE_KEY)


# ── Rename ────────────────────────────────────────────────────────────────────

def rename(game_slug: str, old: str, new: str) -> None:
    if old in SYSTEM_PROFILES:
        raise ValueError(f"Cannot rename system profile: {old}")
    if new in SYSTEM_PROFILES:
        raise ValueError(f"Cannot use reserved name: {new}")
    raw = _load_raw(game_slug)
    profiles = {k: v for k, v in raw.items() if not k.startswith("_")}
    if old not in profiles:
        raise ValueError(f"Profile '{old}' not found")
    if new in profiles:
        raise ValueError(f"Profile '{new}' already exists")
    profiles[new] = profiles.pop(old)
    new_raw = {k: v for k, v in raw.items() if k.startswith("_")}
    if new_raw.get(_ACTIVE_KEY) == old:
        new_raw[_ACTIVE_KEY] = new
    new_raw.update(profiles)
    _save_raw(game_slug, new_raw)


# ── Dirty detection ───────────────────────────────────────────────────────────

def is_dirty(game_slug: str, name: str, current_active: list[str]) -> bool:
    """True when current active mods differ from what was saved in the named profile."""
    entry = get(game_slug, name)
    if entry is None:
        return False
    return set(entry.get("active_mods", [])) != set(current_active)
