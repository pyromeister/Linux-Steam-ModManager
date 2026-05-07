"""LOOT integration — detect and invoke LOOT for Bethesda load order sorting."""

import os
import shutil
import subprocess
from pathlib import Path


def _in_flatpak() -> bool:
    return os.environ.get("FLATPAK_ID") is not None or Path("/.flatpak-info").exists()


_LOOT_FLATPAK_ID = "io.github.loot.loot"

_LOOT_GAME_IDS: dict[str, str] = {
    "skyrim_se": "Skyrim Special Edition",
    "fallout4": "Fallout4",
    "starfield": "Starfield",
    "skyrim_le": "Skyrim",
    "oblivion": "Oblivion",
    "falloutnv": "FalloutNV",
    "fallout3": "Fallout3",
}


def detect_loot() -> list[str] | None:
    """Return command prefix to invoke LOOT, or None if not found.

    Inside a Flatpak sandbox, uses flatpak-spawn --host to reach host
    installations. Outside, checks native loot on PATH first, then Flatpak.
    """
    if _in_flatpak():
        result = subprocess.run(
            ["flatpak-spawn", "--host", "flatpak", "info", _LOOT_FLATPAK_ID],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return ["flatpak-spawn", "--host", "flatpak", "run", _LOOT_FLATPAK_ID]
        return None

    if shutil.which("loot"):
        return ["loot"]
    if shutil.which("flatpak"):
        result = subprocess.run(
            ["flatpak", "info", _LOOT_FLATPAK_ID],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return ["flatpak", "run", _LOOT_FLATPAK_ID]
    return None


def loot_game_id(profile: dict) -> str | None:
    """Return LOOT game identifier for the given profile, or None if unsupported."""
    return _LOOT_GAME_IDS.get(profile.get("slug", ""))


def sort_with_loot(profile: dict, game_root: Path) -> None:
    """Run LOOT --auto-sort for the given game.

    Raises:
        RuntimeError: LOOT not installed or game not in mapping
        subprocess.CalledProcessError: LOOT exits non-zero
        subprocess.TimeoutExpired: LOOT did not exit within 120 s
    """
    cmd = detect_loot()
    if cmd is None:
        raise RuntimeError(
            "LOOT not found. Install via package manager or Flatpak (io.github.loot.loot)."
        )
    game_id = loot_game_id(profile)
    if game_id is None:
        raise RuntimeError(
            f"Game '{profile.get('name', profile.get('slug', '?'))}' not supported by LOOT."
        )
    subprocess.run(
        cmd + ["--game", game_id, "--game-path", str(game_root), "--auto-sort"],
        check=True,
        timeout=120,
    )
