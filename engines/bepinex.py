"""
BepInEx engine plugin — Unity games using the BepInEx mod framework.
Games: The Planet Crafter, Valheim, etc.
Capabilities: install/uninstall, activation toggle (renames .dll ↔ .dll.disabled),
              automatic BepInEx download + install from GitHub releases.
No load order (BepInEx handles plugin ordering internally).
"""

import json
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base import BaseEngine
from config import find_library_for_app
from installer import (
    ConflictError,
    cache_archive,
    check_conflicts,
    extract,
    install_files,
    load_manifest,
    record_install,
    remove_from_manifest,
)

DLL_EXT = ".dll"
BEPINEX_API = "https://api.github.com/repos/BepInEx/BepInEx/releases/latest"
USER_AGENT = "linux-mod-manager/1.0"


class BepInExEngine(BaseEngine):
    has_load_order = False
    has_script_extender = False
    has_activation_toggle = True
    has_framework_setup = True
    framework_name = "BepInEx"

    def __init__(self, profile: dict):
        super().__init__(profile)
        app_id = profile["steam_app_id"]
        subdir = profile["install_subdir"]
        steam_lib = find_library_for_app(app_id) or (Path.home() / ".local/share/Steam")
        self.game_root = steam_lib / "steamapps/common" / subdir
        bepinex_cfg = profile.get("bepinex", {})
        plugins_rel = bepinex_cfg.get("plugins_dir", "BepInEx/plugins")
        self.plugins_dir = self.game_root / plugins_rel
        # proton=True → Windows BepInEx build, winhttp.dll doorstop via Proton
        # proton=False (default) → Linux native build, run_bepinex.sh + libdoorstop.so
        self._proton = profile.get("proton", False)
        if self._proton:
            self._bepinex_build = bepinex_cfg.get("build", "win_x64")
        else:
            self._bepinex_build = bepinex_cfg.get("build", "linux_x64")

    def is_framework_installed(self) -> bool:
        """True if BepInEx core is present in the game root."""
        return (self.game_root / "BepInEx" / "core").exists()

    def setup_launch(self) -> str:
        """
        Return the Steam launch option required to activate BepInEx.
        For Proton games: WINEDLLOVERRIDES env var (winhttp.dll doorstop).
        For native Linux: run_bepinex.sh wrapper (libdoorstop.so).
        Also makes run_bepinex.sh executable when applicable.
        Raises RuntimeError if BepInEx is not installed.
        """
        if not self.is_framework_installed():
            raise RuntimeError("BepInEx is not installed — install it first")

        if self._proton:
            # Proton: winhttp.dll doorstop, no script needed
            return 'WINEDLLOVERRIDES="winhttp=n,b" %command%'
        else:
            # Native Linux: run_bepinex.sh wrapper
            import stat
            launch_script = self.game_root / "run_bepinex.sh"
            if not launch_script.exists():
                raise RuntimeError("run_bepinex.sh not found — reinstall BepInEx")
            mode = launch_script.stat().st_mode
            launch_script.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            return f'"{launch_script}" %command%'

    def verify(self) -> list[str]:
        warnings = []
        if not self.game_root.exists():
            warnings.append(f"Game not found: {self.game_root}")
        if not self.is_framework_installed():
            warnings.append("BepInEx not installed — use 'Setup BepInEx' to install it")
        elif not self._proton and not (self.game_root / "run_bepinex.sh").exists():
            warnings.append("run_bepinex.sh missing — reinstall BepInEx")
        return warnings

    # ── BepInEx auto-install ──────────────────────────────────────────────────

    def setup_framework(self, on_progress=None) -> str:
        """
        Download the latest BepInEx release from GitHub and extract it to game_root.
        Calls on_progress(downloaded_bytes, total_bytes) during download.
        Returns the installed version string.
        Raises RuntimeError on any failure.
        """
        print("Fetching latest BepInEx release info from GitHub...")
        req = urllib.request.Request(
            BEPINEX_API,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                release = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub API error {e.code}: {e.read().decode(errors='replace')}") from e

        version = release.get("tag_name", "unknown")
        assets = release.get("assets", [])

        # Find the right platform asset
        build = self._bepinex_build
        asset = next(
            (a for a in assets if build in a["name"] and a["name"].endswith(".zip")),
            None,
        )
        if asset is None:
            available = [a["name"] for a in assets]
            raise RuntimeError(
                f"No asset matching '{build}' in release {version}. "
                f"Available: {', '.join(available)}"
            )

        dl_url = asset["browser_download_url"]
        filename = asset["name"]
        tmp_zip = Path(f"/tmp/bepinex_{filename}")

        print(f"Downloading {filename} ({version})...")
        dl_req = urllib.request.Request(dl_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(dl_req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with tmp_zip.open("wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)

        print(f"Extracting to {self.game_root}...")
        self.game_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_zip) as z:
            members = z.namelist()
            z.extractall(self.game_root)

        # Track in manifest so it can be uninstalled like any other mod
        installed_files = [
            self.game_root / m
            for m in members
            if not m.endswith("/")  # skip directory entries
        ]
        game_slug = self.profile.get("slug")
        record_install(
            "BepInEx",
            tmp_zip,
            installed_files,
            game_slug=game_slug,
            nexus_meta={"source": "github", "version": version},
        )

        tmp_zip.unlink(missing_ok=True)

        print(f"✓ BepInEx {version} installed to {self.game_root}")
        return version

    # ── Install ──────────────────────────────────────────────────────────────

    def install(
        self,
        archive_path: Path,
        mod_name: str = None,
        force: bool = False,
        nexus_meta: dict | None = None,
    ) -> None:
        """
        Install a mod archive. Archive layout detection:
          - Contains BepInEx/ at root → install relative to game_root
            (handles mods that ship with BepInEx folder structure)
          - Otherwise → install all files into BepInEx/plugins/
            (handles flat DLL-only mods)
        Raises ConflictError if files conflict with another tracked mod (unless force=True).
        """
        name = mod_name or archive_path.stem
        game_slug = self.profile.get("slug")
        tmp = Path(f"/tmp/linuxmm_{name}")
        try:
            print(f"Extracting {archive_path.name}...")
            extract(archive_path, tmp)

            top_names = {p.name.lower(): p for p in tmp.iterdir()}
            if "bepinex" in top_names:
                # Archive has BepInEx/ structure → install relative to game root
                dest_root = self.game_root
                src_root = tmp
            else:
                # Flat archive (DLLs, subdirs) → everything into BepInEx/plugins/
                dest_root = self.plugins_dir
                src_root = tmp

            if not force:
                conflicts = check_conflicts(tmp, dest_root, load_manifest(), name)
                if conflicts:
                    raise ConflictError(conflicts)

            archive_cache = cache_archive(archive_path, game_slug)
            self.plugins_dir.mkdir(parents=True, exist_ok=True)

            print("Installing files...")
            installed, backups = install_files(src_root, dest_root, game_slug, name)

            record_install(name, archive_path, installed, game_slug=game_slug,
                           archive_cache=archive_cache, backups=backups,
                           nexus_meta=nexus_meta)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        print(f"✓ Installed: {name}")

    # ── Uninstall ────────────────────────────────────────────────────────────

    def uninstall(self, mod_name: str) -> None:
        entry = remove_from_manifest(mod_name)
        if not entry:
            print(f"Not installed: {mod_name}")
            return

        backups = entry.get("backups", {})
        for f_str in entry.get("files", []):
            f = Path(f_str)
            bak_str = backups.get(f_str)
            if bak_str:
                bak = Path(bak_str)
                if bak.exists():
                    f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bak, f)
                    bak.unlink()
            else:
                # Also remove disabled variant if present
                disabled = Path(f_str + ".disabled")
                if f.exists():
                    f.unlink()
                elif disabled.exists():
                    disabled.unlink()
            # Remove empty parent directories up to plugins_dir
            try:
                if f.parent != self.plugins_dir and not any(f.parent.iterdir()):
                    f.parent.rmdir()
            except Exception:
                pass

        print(f"✓ Uninstalled: {mod_name}")

    # ── List ─────────────────────────────────────────────────────────────────

    def list_mods(self) -> list[dict]:
        game_slug = self.profile.get("slug")
        manifest = load_manifest()
        result = []
        tracked_dll_names: set[str] = set()

        for name, entry in manifest.items():
            entry_game = entry.get("game")
            if entry_game is not None and entry_game != game_slug:
                continue

            files = entry.get("files", [])
            # Active = no tracked .dll is currently renamed to .dll.disabled
            active = True
            for f_str in files:
                p = Path(f_str)
                if p.suffix.lower() == DLL_EXT:
                    tracked_dll_names.add(p.name)
                    if not p.exists() and Path(f_str + ".disabled").exists():
                        active = False

            # BepInEx itself gets a special "framework" kind
            kind = "framework" if name == "BepInEx" else "mod"
            result.append({"name": name, "active": active, "plugins": [], "kind": kind})

        # If BepInEx is installed on disk but not in manifest, show it as untracked
        bepinex_tracked = any(e.get("name") == "BepInEx" or n == "BepInEx"
                              for n, e in manifest.items()
                              if e.get("game") in (None, game_slug))
        if not bepinex_tracked and self.is_framework_installed():
            result.insert(0, {
                "name": "BepInEx",
                "active": True,
                "plugins": [],
                "kind": "framework",
                "untracked": True,
            })

        # Show untracked DLLs found in plugins_dir (manually dropped in)
        if self.plugins_dir.exists():
            for dll in sorted(self.plugins_dir.glob(f"*{DLL_EXT}")):
                if dll.name not in tracked_dll_names:
                    result.append({"name": dll.stem, "active": True, "plugins": [], "kind": "se_plugin"})

        return result

    # ── Activation ───────────────────────────────────────────────────────────

    def enable_mod(self, mod_name: str) -> None:
        manifest = load_manifest()
        if mod_name not in manifest:
            return
        for f_str in manifest[mod_name].get("files", []):
            if f_str.endswith(DLL_EXT):
                disabled = Path(f_str + ".disabled")
                if disabled.exists():
                    disabled.rename(Path(f_str))
        print(f"✓ enabled: {mod_name}")

    def disable_mod(self, mod_name: str) -> None:
        manifest = load_manifest()
        if mod_name not in manifest:
            return
        for f_str in manifest[mod_name].get("files", []):
            p = Path(f_str)
            if p.suffix.lower() == DLL_EXT and p.exists():
                p.rename(Path(f_str + ".disabled"))
        print(f"✓ disabled: {mod_name}")
