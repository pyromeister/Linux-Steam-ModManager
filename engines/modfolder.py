"""
ModFolder engine — games where mods are folders dropped into a Mods/ directory.
Games: Stardew Valley (SMAPI), 7 Days to Die, and similar drop-in mod systems.
Capabilities: install/uninstall, activation toggle (appends .disabled to files).
No framework setup, no load order (handled by the game / mod loader itself).
"""

import shutil
import sys
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


class ModFolderEngine(BaseEngine):
    has_load_order = False
    has_script_extender = False
    has_activation_toggle = True
    has_framework_setup = False

    def __init__(self, profile: dict):
        super().__init__(profile)
        app_id = profile["steam_app_id"]
        subdir = profile["install_subdir"]
        steam_lib = find_library_for_app(app_id) or (Path.home() / ".local/share/Steam")
        self.game_root = steam_lib / "steamapps/common" / subdir
        mods_rel = profile.get("modfolder", {}).get("mods_dir", "Mods")
        self.mods_dir = self.game_root / mods_rel
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
        mod_name: str = None,
        force: bool = False,
        nexus_meta: dict | None = None,
    ) -> None:
        name = mod_name or archive_path.stem
        game_slug = self.profile.get("slug")
        tmp = Path(f"/tmp/linuxmm_{name}")
        try:
            print(f"Extracting {archive_path.name}...")
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

            print("Installing files...")
            installed, backups = install_files(src_root, dest, game_slug, name)
            record_install(
                name, archive_path, installed,
                game_slug=game_slug, archive_cache=archive_cache,
                backups=backups, nexus_meta=nexus_meta,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        print(f"✓ Installed: {name}")

    # ── Uninstall ─────────────────────────────────────────────────────────────

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
                for candidate in (f, Path(str(f) + ".disabled")):
                    if candidate.exists():
                        candidate.unlink()
            # Clean empty parent dirs up to mods_dir
            try:
                if f.parent != self.mods_dir and f.parent.exists() and not any(f.parent.iterdir()):
                    f.parent.rmdir()
            except Exception:
                pass

        print(f"✓ Uninstalled: {mod_name}")

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
            result.append({"name": mod_name, "active": active, "kind": "mod"})

        # Show untracked subdirectories in mods_dir
        if self.mods_dir.exists():
            for d in sorted(self.mods_dir.iterdir()):
                if not d.is_dir():
                    continue
                is_disabled = d.name.endswith(".disabled")
                base_name = d.name.removesuffix(".disabled")
                if base_name not in tracked_names and base_name not in tracked_dirs:
                    result.append({
                        "name": base_name,
                        "active": not is_disabled,
                        "kind": "mod",
                        "untracked": True,
                    })

        return result

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
        print(f"✓ enabled: {mod_name}")

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
        print(f"✓ disabled: {mod_name}")
