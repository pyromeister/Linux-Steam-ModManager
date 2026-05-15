"""ScriptExtenderManager — generic SE install/update/uninstall for any engine plugin."""

import json
from pathlib import Path

from lsmm.core import net
from lsmm.core.config import (
    clear_se_installed_version,
    get_se_installed_version,
    save_se_installed_version,
)
from lsmm.core.installer import extract
from lsmm.core.nexus import download_file


def fetch_github_latest_tag(repo: str) -> str | None:
    """Return latest release tag (version stripped of leading 'v') or None on failure."""
    try:
        data = net.request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        return json.loads(data).get("tag_name", "").lstrip("v") or None
    except Exception:
        return None


class ScriptExtenderManager:
    """Manages a script extender / framework for a single game.

    Accepts the `script_extender` sub-dict from a game profile plus the
    resolved game root path and game slug. All SE operations delegate here
    so engine plugins don't duplicate this logic.
    """

    def __init__(self, se_profile: dict, game_root: Path, game_slug: str) -> None:
        self._se = se_profile
        self._game_root = game_root
        self._slug = game_slug

    # ── Queries ──────────────────────────────────────────────────────────────

    def is_installed(self) -> bool:
        loader = self._se.get("loader_exe", "")
        if not loader:
            return False
        return (self._game_root / loader).exists()

    def get_installed_version(self) -> str | None:
        """Version from config (written on install), falling back to DLL filename heuristic.

        Config is preferred because some SEs (e.g. NVSE) name their DLLs after the
        game version they target (nvse_1_4.dll = game v1.4), not the SE version.
        """
        config_ver = get_se_installed_version(self._slug) if self._slug else None
        if config_ver:
            return config_ver
        prefix = self._se.get("asset_prefix", "")
        if prefix and self._game_root.exists():
            loader = self._se.get("loader_exe", "")
            for dll in self._game_root.glob(f"{prefix}*.dll"):
                if loader and dll.name == loader:
                    continue
                stem = dll.stem[len(prefix):]
                if stem and all(p.isdigit() for p in stem.split("_")):
                    return stem.replace("_", ".")
        return None

    def get_latest_info(self) -> tuple[str, str, str] | None:
        """Fetch latest GitHub release. Returns (version, download_url, filename) or None."""
        repo = self._se.get("github_repo")
        prefix = self._se.get("asset_prefix", "")
        if not repo:
            return None
        try:
            data = net.request(
                f"https://api.github.com/repos/{repo}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            release = json.loads(data)
        except Exception:
            return None
        version = release.get("tag_name", "unknown")
        for asset in release.get("assets", []):
            name = asset["name"]
            if name.startswith(prefix) and name.endswith((".7z", ".zip")):
                return version, asset["browser_download_url"], name
        return None

    # ── Mutating ─────────────────────────────────────────────────────────────

    def download(self, on_progress=None) -> None:
        """Download latest SE from GitHub, extract to game root, save version to config."""
        info = self.get_latest_info()
        if info is None:
            raise RuntimeError("Could not fetch SE release info from GitHub")
        version, url, filename = info
        tmp = Path(f"/tmp/{filename}")
        download_file(url, tmp, on_progress=on_progress)
        self._game_root.mkdir(parents=True, exist_ok=True)
        extract(tmp, self._game_root)
        tmp.unlink(missing_ok=True)
        if self._slug:
            save_se_installed_version(self._slug, version.lstrip("v"))

    def uninstall(self) -> None:
        """Remove SE files from game root. Never touches user plugin directories."""
        prefix = self._se.get("asset_prefix", "")
        loader = self._se.get("loader_exe", "")
        removed = False
        if prefix and self._game_root.exists():
            for f in self._game_root.glob(f"{prefix}*"):
                if f.suffix.lower() in (".dll", ".exe"):
                    f.unlink(missing_ok=True)
                    removed = True
        if loader and self._game_root.exists():
            target = self._game_root / loader
            if target.exists():
                target.unlink()
                removed = True
        if removed and self._slug:
            clear_se_installed_version(self._slug)
