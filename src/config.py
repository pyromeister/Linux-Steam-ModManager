"""
Path resolver — generic, reads game profile from games/*.json.
No hardcoded game paths. All paths derived from Steam layout + profile.
"""

import json
import re
import sys
from pathlib import Path

GAMES_DIR = Path(__file__).parent.parent / "games"
APP_CONFIG_PATH = Path.home() / ".config/linux-mod-manager/config.json"
ARCHIVES_DIR = Path.home() / ".local/share/linux-mod-manager/archives"
BACKUPS_DIR = Path.home() / ".local/share/linux-mod-manager/backups"

# Known Steam data dir locations, checked in order of preference
_STEAM_CANDIDATES = [
    Path.home() / ".local/share/Steam",                            # native / .deb / .rpm
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",  # Flatpak
    Path.home() / "snap/steam/common/.local/share/Steam",         # Snap
]


# ── App config (persists user choices across sessions) ────────────────────────

def _load_app_config() -> dict:
    if APP_CONFIG_PATH.exists():
        try:
            return json.loads(APP_CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_app_config(data: dict) -> None:
    APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    APP_CONFIG_PATH.write_text(json.dumps(data, indent=2))


def save_steam_root(path: Path) -> None:
    """Persist the user-chosen Steam root to app config."""
    config = _load_app_config()
    config["steam_root"] = str(path)
    _save_app_config(config)


def get_nexus_api_key() -> str | None:
    return _load_app_config().get("nexus_api_key")


def save_nexus_api_key(key: str) -> None:
    config = _load_app_config()
    config["nexus_api_key"] = key.strip()
    _save_app_config(config)


# ── Steam root detection ──────────────────────────────────────────────────────

def get_steam_candidates() -> list[Path]:
    """All auto-detectable Steam data directories present on this system."""
    return [c for c in _STEAM_CANDIDATES if (c / "steamapps").exists()]


def get_steam_root() -> Path | None:
    """
    Return the Steam data directory to use, or None if ambiguous / not found.

    Priority:
      1. Saved config  (validated: steamapps must still exist)
      2. Auto-detected (only when exactly one candidate is found)
      3. None          (0 or 2+ candidates, no saved config) → caller must prompt
    """
    config = _load_app_config()
    if "steam_root" in config:
        saved = Path(config["steam_root"])
        if (saved / "steamapps").exists():
            return saved
        # Saved path no longer valid — drop it and re-detect
        del config["steam_root"]
        _save_app_config(config)

    candidates = get_steam_candidates()
    if len(candidates) == 1:
        return candidates[0]
    return None  # 0 or multiple — GUI must ask the user


def _parse_library_paths(vdf_path: Path) -> list[Path]:
    """Extract all 'path' values from libraryfolders.vdf (regex, no full VDF parser needed)."""
    if not vdf_path.exists():
        return []
    content = vdf_path.read_text(encoding="utf-8")
    return [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', content)]


def find_library_for_app(app_id: str | int) -> Path | None:
    """
    Return the Steam library folder that contains the given app ID,
    detected via appmanifest_{app_id}.acf presence.
    Searches all libraries listed in libraryfolders.vdf.
    Falls back to the Steam root itself if no manifest found.
    """
    steam_root = get_steam_root()
    if steam_root is None:
        return None

    vdf = steam_root / "steamapps/libraryfolders.vdf"
    libraries = _parse_library_paths(vdf) or [steam_root]

    for lib in libraries:
        if (lib / f"steamapps/appmanifest_{app_id}.acf").exists():
            return lib

    return steam_root  # game not found in any library — fall back to root


def load_profile(game: str) -> dict:
    """Load game profile from games/<game>.json."""
    path = GAMES_DIR / f"{game}.json"
    if not path.exists():
        available = [p.stem for p in GAMES_DIR.glob("*.json")]
        raise FileNotFoundError(
            f"No profile for '{game}'. Available: {', '.join(available)}"
        )
    return json.loads(path.read_text())


class GamePaths:
    """Resolves all relevant paths for a game from its profile."""

    def __init__(self, profile: dict):
        self.profile = profile
        app_id = profile["steam_app_id"]
        subdir = profile["install_subdir"]

        steam_lib = find_library_for_app(app_id) or (Path.home() / ".local/share/Steam")
        self.game_root = steam_lib / "steamapps/common" / subdir
        self.data_dir = self.game_root / "Data"
        self.proton_prefix = steam_lib / f"steamapps/compatdata/{app_id}/pfx"
        self.drive_c = self.proton_prefix / "drive_c"

        # Script extender
        se = profile.get("script_extender")
        self.script_extender = se
        if se:
            self.se_loader = self.game_root / se["loader_exe"]
            self.se_plugins_dir = self.game_root / se["plugins_dir"]
        else:
            self.se_loader = None
            self.se_plugins_dir = None

    @property
    def plugins_txt(self) -> Path:
        """Plugins.txt — in Proton AppData (Bethesda games)."""
        name = self.profile["name"]
        return (
            self.drive_c
            / "users/steamuser/AppData/Local"
            / name
            / "Plugins.txt"
        )

    @property
    def custom_ini(self) -> Path:
        """StarfieldCustom.ini (or equivalent) in Proton My Games."""
        name = self.profile["name"]
        return (
            self.drive_c
            / "users/steamuser/Documents/My Games"
            / name
            / f"{name}Custom.ini"
        )

    def verify(self) -> list[str]:
        """Return list of warning strings for missing paths."""
        warnings = []
        if not self.game_root.exists():
            warnings.append(f"Game not found: {self.game_root}")
        if not self.data_dir.exists():
            warnings.append(f"Data dir missing: {self.data_dir}")
        if self.se_loader and not self.se_loader.exists():
            se_name = self.profile["script_extender"]["name"]
            warnings.append(f"{se_name} loader not found: {self.se_loader}")
        return warnings


# Case normalization map — Linux-only (ext4 is case-sensitive, Windows NTFS is not)
# Mods packed on Windows ship wrong-cased dirs that silently fail on Linux.
CANONICAL_DIR_NAMES: dict[str, str] = {
    "interface": "Interface",
    "textures": "Textures",
    "scripts": "Scripts",
    "meshes": "Meshes",
    "sound": "Sound",
    "music": "Music",
    "video": None,  # vanilla Starfield uses lowercase — do NOT rename
    "sfse": "SFSE",
    "skse": "SKSE",
    "f4se": "F4SE",
    "plugins": "Plugins",  # inside SFSE/SKSE/F4SE dirs
}


def normalize_dir_name(name: str) -> str | None:
    """
    Return canonical casing for a known directory name.
    Returns None if name should not be renamed (e.g. vanilla 'video').
    Returns the input unchanged if it's not in the map.
    """
    if sys.platform == "win32":
        return name  # NTFS is case-insensitive, no fix needed
    lower = name.lower()
    if lower in CANONICAL_DIR_NAMES:
        canonical = CANONICAL_DIR_NAMES[lower]
        return canonical if canonical is not None else name
    return name
