"""
ModFolder engine — games where mods are folders dropped into a Mods/ directory.
Games: Stardew Valley (SMAPI), 7 Days to Die, and similar drop-in mod systems.
Capabilities: install/uninstall, activation toggle (appends .disabled to files).
No framework setup, no load order (handled by the game / mod loader itself).
"""

import io
import json
import logging
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


from lsmm.core import net
from lsmm.engines.base import BaseEngine
from lsmm.core.config import find_library_for_app, get_path_overrides
from lsmm.core.installer import (
    ConflictError,
    cache_archive,
    check_conflicts,
    extract,
    install_files,
    load_manifest,
    record_install,
    remove_from_manifest,
    safe_archive_member_path,
    temp_extract_dir,
)


USER_AGENT = "linux-mod-manager/1.0"


def _parse_smapi_manifest(path: Path) -> dict | None:
    """Parse a SMAPI manifest.json tolerantly: handles BOM, // comments, trailing commas."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            raw = path.read_text(encoding=enc, errors="replace")
            raw = re.sub(r"//[^\n]*", "", raw)
            raw = re.sub(r",\s*([\}\]])", r"\1", raw)
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


GITHUB_API = "https://api.github.com/repos"

logger = logging.getLogger(__name__)


class ModFolderEngine(BaseEngine):
    has_load_order = False
    has_script_extender = False
    has_activation_toggle = True

    @property
    def framework_name(self) -> str:
        return "SMAPI"

    @property
    def has_framework_setup(self) -> bool:
        return bool(self.profile.get("smapi"))

    def is_framework_installed(self) -> bool:
        smapi = self.profile.get("smapi", {})
        exe = smapi.get("executable", "StardewModdingAPI")
        return (self.game_root / exe).exists()

    def setup_launch(self) -> str:
        if not self.is_framework_installed():
            raise RuntimeError("SMAPI not installed — install it first")
        smapi = self.profile.get("smapi", {})
        launch = smapi.get("launch_script") or smapi.get("executable", "StardewModdingAPI")
        path = self.game_root / launch
        if not path.exists():
            raise RuntimeError(f"{launch} not found — reinstall SMAPI")
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        # SMAPI_USE_CURRENT_SHELL: run SMAPI in Steam's process instead of
        # opening a new terminal window, so Steam tracks the game correctly.
        return f'SMAPI_USE_CURRENT_SHELL=true "{path}" %command%'

    def setup_framework(self, on_progress=None) -> str:
        smapi = self.profile.get("smapi", {})
        repo = smapi["github_repo"]
        asset_name = smapi["asset_name"]
        installer_subdir = smapi["installer_subdir"]
        install_dat = smapi["install_dat"]
        exe = smapi.get("executable", "StardewModdingAPI")

        release = json.loads(net.request(
            f"{GITHUB_API}/{repo}/releases/latest",
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        ))
        version = release["tag_name"]

        asset = next(
            (a for a in release["assets"]
             if asset_name in a["name"] and "double" not in a["name"]),
            None,
        )
        if not asset:
            raise RuntimeError(f"No SMAPI installer asset found in release {version}")

        tmp_file = tempfile.NamedTemporaryFile(
            prefix="lsmm_smapi_",
            suffix="_installer.zip",
            delete=False,
        )
        tmp_zip = Path(tmp_file.name)
        tmp_file.close()

        try:
            dl_req = urllib.request.Request(
                asset["browser_download_url"],
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(dl_req, timeout=120) as resp:
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

            with zipfile.ZipFile(tmp_zip) as outer:
                dat_path = next(
                    m for m in outer.namelist()
                    if m.endswith(f"{installer_subdir}/{install_dat}")
                )
                inner_bytes = outer.read(dat_path)

            self.game_root.mkdir(parents=True, exist_ok=True)
            installed_files = []
            with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
                file_members = [m for m in inner.namelist() if not m.endswith("/")]
                for m in file_members:
                    safe_archive_member_path(self.game_root, m)
                for m in file_members:
                    dest = safe_archive_member_path(self.game_root, m)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(inner.read(m))
                    installed_files.append(dest)

            for make_exec in [exe, smapi.get("launch_script", "")]:
                if make_exec:
                    p = self.game_root / make_exec
                    if p.exists():
                        p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

            # SMAPI's install.dat doesn't include StardewModdingAPI.deps.json — the
            # official installer generates it by copying the game's deps file. Without
            # it the dotnet apphost falls into split/FX mode and shows help text instead
            # of launching. Copy game deps.json so the host can resolve assemblies.
            game_deps = self.game_root / "Stardew Valley.deps.json"
            smapi_deps = self.game_root / f"{exe}.deps.json"
            if game_deps.exists() and not smapi_deps.exists():
                shutil.copy2(game_deps, smapi_deps)
                installed_files.append(smapi_deps)

            record_install(
                "SMAPI",
                tmp_zip,
                installed_files,
                game_slug=self.profile.get("slug"),
                nexus_meta={"source": "github", "version": version},
            )
        finally:
            tmp_zip.unlink(missing_ok=True)
        return version

    def __init__(self, profile: dict):
        super().__init__(profile)
        app_id = profile["steam_app_id"]
        subdir = profile["install_subdir"]
        steam_lib = find_library_for_app(app_id) or (Path.home() / ".local/share/Steam")
        self.game_root = steam_lib / "steamapps/common" / subdir
        mods_rel = profile.get("modfolder", {}).get("mods_dir", "Mods")
        self.mods_dir = self.game_root / mods_rel
        ov = get_path_overrides(str(app_id))
        if ov.get("game_root"):
            self.game_root = Path(ov["game_root"])
            self.mods_dir = self.game_root / mods_rel
        if ov.get("mods_dir"):
            self.mods_dir = Path(ov["mods_dir"])
        self.paths = self  # cmd_check calls engine.paths.verify()

    def verify(self) -> list[str]:
        warnings = []
        if not self.game_root.exists():
            warnings.append(f"Game not found: {self.game_root}")
        elif not self.mods_dir.exists():
            warnings.append(f"Mods directory not found: {self.mods_dir} — will be created on first install")
        return warnings

    # ── Install ───────────────────────────────────────────────────────────────

    def install(
        self,
        archive_path: Path,
        mod_name: str | None = None,
        force: bool = False,
        nexus_meta: dict | None = None,
        fomod_files: list[tuple[str, str]] | None = None,
    ) -> None:
        name = mod_name or archive_path.stem
        game_slug = self.profile.get("slug")
        with temp_extract_dir() as tmp:
            logger.info(f"Extracting {archive_path.name}...")
            extract(archive_path, tmp)

            tops = [p for p in tmp.iterdir()]
            if len(tops) == 1 and tops[0].is_dir():
                # Single top-level folder — use the folder's real name as the
                # manifest key so list_mods() shows the mod name, not the archive filename.
                src_root = tops[0]
                folder_name = mod_name or tops[0].name
                dest = self.mods_dir / folder_name
                name = folder_name
            else:
                # Multiple entries — bundle everything into a named subfolder
                src_root = tmp
                dest = self.mods_dir / name

            if not force:
                conflicts = check_conflicts(tmp, self.mods_dir, load_manifest(), name)
                if conflicts:
                    raise ConflictError(conflicts)

            archive_cache = cache_archive(archive_path, game_slug)
            self.mods_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Installing files...")
            installed, backups = install_files(src_root, dest, game_slug, name)
            record_install(
                name, archive_path, installed,
                game_slug=game_slug, archive_cache=archive_cache,
                backups=backups, nexus_meta=nexus_meta,
            )

        logger.info(f"✓ Installed: {name}")

    # ── Uninstall ─────────────────────────────────────────────────────────────

    def uninstall(self, mod_name: str) -> None:
        entry = load_manifest().get(mod_name)
        if not entry:
            logger.warning(f"Not installed: {mod_name}")
            return

        failed: list[str] = []
        backups = entry.get("backups", {})
        for f_str in entry.get("files", []):
            f = Path(f_str)
            bak_str = backups.get(f_str)
            try:
                if bak_str:
                    bak = Path(bak_str)
                    if bak.exists():
                        f.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(bak, f)
                        bak.unlink()
                else:
                    for candidate in (f, Path(str(f) + ".disabled")):
                        if candidate.exists():
                            candidate.unlink()
            except OSError as e:
                logger.warning("Could not remove %s: %s", f, e)
                failed.append(f_str)
            # Clean empty parent dirs up to mods_dir
            try:
                parent = f.parent
                while parent != self.mods_dir and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            except Exception:
                pass

        if failed:
            logger.warning("Partial uninstall of %s — %d file(s) not removed: %s",
                           mod_name, len(failed), failed)
        else:
            remove_from_manifest(mod_name)
            logger.info(f"✓ Uninstalled: {mod_name}")

    # ── List ──────────────────────────────────────────────────────────────────

    def list_mods(self) -> list[dict]:
        game_slug = self.profile.get("slug")
        manifest = load_manifest()
        result = []
        tracked_names: set[str] = set()
        tracked_dirs: set[str] = set()

        for mod_name, entry in manifest.items():
            if entry.get("game") not in (None, game_slug):
                continue
            files = entry.get("files", [])
            # Skip entries whose files belong to a different game_root (stale override)
            if files and not any(Path(f).is_relative_to(self.game_root) for f in files):
                continue
            active = not any(
                not Path(f).exists() and Path(str(f) + ".disabled").exists()
                for f in files
            )
            tracked_names.add(mod_name)
            # Collect top-level installed dir names so the directory scan
            # doesn't show them as untracked duplicates.
            for f_str in files:
                try:
                    rel = Path(f_str).relative_to(self.mods_dir)
                    if rel.parts:
                        tracked_dirs.add(rel.parts[0].removesuffix(".disabled"))
                except ValueError:
                    pass
            fw = self.framework_name if self.has_framework_setup else None
            kind = "framework" if mod_name == fw else "mod"
            result.append({"name": mod_name, "active": active, "kind": kind, "nexus": entry.get("nexus")})

        # Show untracked subdirectories in mods_dir
        if self.mods_dir.exists():
            for d in sorted(self.mods_dir.iterdir()):
                if not d.is_dir():
                    continue
                is_disabled = d.name.endswith(".disabled")
                base_name = d.name.removesuffix(".disabled")
                if base_name in tracked_names or base_name in tracked_dirs:
                    continue
                # Skip SMAPI-bundled internal mods (UniqueID starts with "SMAPI.")
                manifest_path = d / "manifest.json"
                if manifest_path.exists():
                    parsed = _parse_smapi_manifest(manifest_path)
                    if parsed and parsed.get("UniqueID", "").startswith("SMAPI."):
                        continue
                result.append({
                    "name": base_name,
                    "active": not is_disabled,
                    "kind": "mod",
                    "untracked": True,
                })

        return result

    # ── Nexus ID detection (SMAPI UpdateKeys) ─────────────────────────────────

    def filesystem_nexus_ids(self) -> set[int]:
        """Return nexus mod IDs from SMAPI manifest.json UpdateKeys in the Mods dir.
        Covers mods installed outside lsmm (e.g. via SMAPI installer or manually)."""
        ids: set[int] = set()
        if not self.mods_dir.exists():
            return ids
        for manifest_path in self.mods_dir.glob("*/manifest.json"):
            data = _parse_smapi_manifest(manifest_path)
            if not data:
                continue
            for key in data.get("UpdateKeys") or []:
                m = re.match(r"Nexus:(\d+)", str(key), re.I)
                if m:
                    ids.add(int(m.group(1)))
        return ids

    # ── Activation ────────────────────────────────────────────────────────────

    def enable_mod(self, mod_name: str) -> None:
        manifest = load_manifest()
        if mod_name in manifest:
            for f_str in manifest[mod_name].get("files", []):
                disabled = Path(str(f_str) + ".disabled")
                if disabled.exists():
                    disabled.rename(Path(f_str))
        else:
            disabled_dir = self.mods_dir / f"{mod_name}.disabled"
            if disabled_dir.exists():
                disabled_dir.rename(self.mods_dir / mod_name)
        logger.info(f"✓ enabled: {mod_name}")

    def disable_mod(self, mod_name: str) -> None:
        manifest = load_manifest()
        if mod_name in manifest:
            for f_str in manifest[mod_name].get("files", []):
                p = Path(f_str)
                if p.exists():
                    p.rename(Path(str(f_str) + ".disabled"))
        else:
            active_dir = self.mods_dir / mod_name
            if active_dir.exists():
                active_dir.rename(self.mods_dir / f"{mod_name}.disabled")
        logger.info(f"✓ disabled: {mod_name}")
