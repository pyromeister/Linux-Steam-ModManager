"""Proton detection and direct-launch helpers."""

import os
import re
from pathlib import Path

from lsmm.core.config import get_all_library_paths


def _in_flatpak() -> bool:
    return os.environ.get("FLATPAK_ID") is not None or Path("/.flatpak-info").exists()


def _parse_compat_tool_name(steam_root: Path, app_id: str) -> str | None:
    """Return the CompatToolMapping tool name for app_id, or None."""
    config_path = steam_root / "config/config.vdf"
    if not config_path.exists():
        return None
    lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()

    state = "scan"
    compat_depth = 0
    app_depth = 0

    for line in lines:
        s = line.strip()
        if state == "scan":
            if s == '"CompatToolMapping"':
                state = "found_compat_key"
        elif state == "found_compat_key":
            if s == "{":
                state = "in_compat"
                compat_depth = 1
        elif state == "in_compat":
            if s == "{":
                compat_depth += 1
            elif s == "}":
                compat_depth -= 1
                if compat_depth == 0:
                    return None
            elif s == f'"{app_id}"' and compat_depth == 1:
                state = "found_app_key"
        elif state == "found_app_key":
            if s == "{":
                state = "in_app"
                app_depth = 1
        elif state == "in_app":
            if s == "{":
                app_depth += 1
            elif s == "}":
                app_depth -= 1
                if app_depth == 0:
                    return None
            else:
                m = re.match(r'"name"\s+"([^"]*)"', s)
                if m:
                    return m.group(1) or None
    return None


def _resolve_proton_dir(steam_root: Path, tool_name: str) -> Path | None:
    """Find the `proton` script for a given tool name."""
    for lib in get_all_library_paths(steam_root):
        candidate = lib / "steamapps/common" / tool_name / "proton"
        if candidate.exists():
            return candidate

    # Steam root may not always appear in libraryfolders.vdf
    candidate = steam_root / "steamapps/common" / tool_name / "proton"
    if candidate.exists():
        return candidate

    # Community tools (GE-Proton, etc.) live in compatibilitytools.d
    compat_dir = steam_root / "compatibilitytools.d"
    if compat_dir.exists():
        candidate = compat_dir / tool_name / "proton"
        if candidate.exists():
            return candidate

    return None


def find_proton_for_game(steam_root: Path, app_id: str) -> Path | None:
    """Return path to the `proton` script assigned to app_id, or None."""
    tool_name = _parse_compat_tool_name(steam_root, app_id)
    if not tool_name:
        return None
    return _resolve_proton_dir(steam_root, tool_name)


def build_proton_launch_cmd(
    proton_path: Path,
    loader_exe: Path,
    app_id: str,
    steam_root: Path,
    compat_data_path: Path,
) -> tuple[list[str], dict[str, str]]:
    """Return (cmd, env_vars) for launching loader_exe via Proton.

    Inside Flatpak the env vars are baked into the flatpak-spawn command and
    env_vars is empty. Outside Flatpak, caller merges env_vars into os.environ.
    """
    env_vars = {
        "STEAM_COMPAT_DATA_PATH": str(compat_data_path),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(steam_root),
        "STEAM_APP_ID": app_id,
    }
    base_cmd = [str(proton_path), "waitforexitandrun", str(loader_exe)]

    if _in_flatpak():
        env_flags = [f"--env={k}={v}" for k, v in env_vars.items()]
        return ["flatpak-spawn", "--host"] + env_flags + base_cmd, {}

    return base_cmd, env_vars
