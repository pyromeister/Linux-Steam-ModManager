"""
Path resolver — generic, reads game profile from games/*.json.
No hardcoded game paths. All paths derived from Steam layout + profile.
"""

import json
import sys
from pathlib import Path

STEAM_ROOT = Path.home() / ".local/share/Steam"
GAMES_DIR = Path(__file__).parent.parent / "games"


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

        self.game_root = STEAM_ROOT / "steamapps/common" / subdir
        self.data_dir = self.game_root / "Data"
        self.proton_prefix = STEAM_ROOT / f"steamapps/compatdata/{app_id}/pfx"
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
