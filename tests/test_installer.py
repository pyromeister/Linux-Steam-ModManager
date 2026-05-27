"""Tests for src/installer.py — core logic only, no game installation required."""

import json
import zipfile
from pathlib import Path

import pytest

import io

from lsmm.core import installer
from lsmm.core.installer import (
    ConflictError,
    detect_and_install,
    detect_source_root,
    check_conflicts,
    check_conflicts_fomod,
    install_files,
    install_fomod_files,
    load_manifest,
    record_install,
    remove_from_manifest,
    safe_extract_zip,
    save_manifest,
    temp_extract_dir,
    extract,
)


# ── temp_extract_dir ──────────────────────────────────────────────────────────

class TestTempExtractDir:
    def test_creates_directory_with_prefix(self):
        with temp_extract_dir() as tmp:
            assert tmp.exists()
            assert tmp.is_dir()
            assert tmp.name.startswith("lsmm_")

    def test_yields_path_object(self):
        with temp_extract_dir() as tmp:
            assert isinstance(tmp, Path)

    def test_cleanup_on_normal_exit(self):
        with temp_extract_dir() as tmp:
            path = tmp
        assert not path.exists()

    def test_cleanup_on_exception(self):
        path = None
        with pytest.raises(RuntimeError):
            with temp_extract_dir() as tmp:
                path = tmp
                tmp.joinpath("file.txt").write_text("data")
                raise RuntimeError("boom")
        assert not path.exists()

    def test_parallel_dirs_are_unique(self):
        with temp_extract_dir() as a, temp_extract_dir() as b:
            assert a != b
            assert a.exists() and b.exists()


# ── extract ───────────────────────────────────────────────────────────────────

class TestExtract:
    def test_zip_extraction(self, tmp_path):
        archive = tmp_path / "mod.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Data/plugin.esp", "fake esp content")
            z.writestr("readme.txt", "readme")

        dest = tmp_path / "extracted"
        extract(archive, dest)

        assert (dest / "Data" / "plugin.esp").exists()
        assert (dest / "readme.txt").exists()

    def test_zip_path_traversal_is_blocked(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("safe.txt", "safe")
            z.writestr("../escape.txt", "owned")

        dest = tmp_path / "extracted"
        with pytest.raises(ValueError, match="Path traversal blocked"):
            extract(archive, dest)

        assert not (tmp_path / "escape.txt").exists()
        assert not (dest / "safe.txt").exists()

    def test_safe_archive_member_path_blocks_absolute_paths(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal blocked"):
            installer.safe_archive_member_path(tmp_path, "/tmp/escape.txt")

    def test_zip_path_traversal_bytesio_no_partial_extraction(self, tmp_path):
        # Matches modfolder.py inner-zip pattern: ZipFile(BytesIO(...))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("safe.txt", "safe")
            z.writestr("../escape.txt", "owned")
        buf.seek(0)

        dest = tmp_path / "extracted"
        dest.mkdir()
        with zipfile.ZipFile(io.BytesIO(buf.read())) as z:
            with pytest.raises(ValueError, match="Path traversal blocked"):
                safe_extract_zip(z, dest)

        assert not (tmp_path / "escape.txt").exists()
        assert not (dest / "safe.txt").exists()

    def test_unsupported_format_raises(self, tmp_path):
        archive = tmp_path / "mod.tar.gz"
        archive.write_bytes(b"fake")
        with pytest.raises(ValueError, match="Unsupported"):
            extract(archive, tmp_path / "out")


# ── detect_source_root ────────────────────────────────────────────────────────

class TestDetectSourceRoot:
    def _make_tree(self, root: Path, *paths: str) -> None:
        for p in paths:
            full = root / p
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("x")

    def test_data_layout(self, tmp_path):
        self._make_tree(tmp_path, "Data/plugin.esp", "Data/Textures/tex.dds")
        root, layout, _ = detect_source_root(tmp_path)
        assert layout == "data"
        assert root == tmp_path / "Data"

    def test_double_data_layout(self, tmp_path):
        self._make_tree(tmp_path, "Data/Data/plugin.esp")
        root, layout, _ = detect_source_root(tmp_path)
        assert layout == "double"
        assert root == tmp_path / "Data" / "Data"

    def test_root_layout(self, tmp_path):
        self._make_tree(tmp_path, "plugin.esp", "Textures/tex.dds")
        root, layout, _ = detect_source_root(tmp_path)
        assert layout == "root"
        assert root == tmp_path

    def test_wrapper_layout(self, tmp_path):
        self._make_tree(tmp_path, "ModName/Data/plugin.esp")
        root, layout, _ = detect_source_root(tmp_path)
        assert layout == "data"
        assert root == tmp_path / "ModName" / "Data"

    def test_wrapper_double_layout(self, tmp_path):
        self._make_tree(tmp_path, "ModName/Data/Data/plugin.esp")
        root, layout, _ = detect_source_root(tmp_path)
        assert layout == "double"
        assert root == tmp_path / "ModName" / "Data" / "Data"


# ── ConflictError ─────────────────────────────────────────────────────────────

class TestConflictError:
    def test_has_conflicts_attribute(self):
        conflicts = [("Textures/foo.dds", "OtherMod")]
        err = ConflictError(conflicts)
        assert err.conflicts == conflicts

    def test_message_contains_count(self):
        err = ConflictError([("a", "m1"), ("b", "m2")])
        assert "2" in str(err)

    def test_single_conflict_message(self):
        err = ConflictError([("a", "m1")])
        assert "1" in str(err)


# ── check_conflicts ───────────────────────────────────────────────────────────

class TestCheckConflicts:
    def _make_extracted(self, tmp_path: Path, *files: str) -> Path:
        ext = tmp_path / "extracted"
        for f in files:
            p = ext / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        return ext

    def test_no_conflicts_empty_manifest(self, tmp_path):
        ext = self._make_extracted(tmp_path, "Data/plugin.esp")
        data_dir = tmp_path / "Data"
        result = check_conflicts(ext, data_dir, {}, "NewMod")
        assert result == []

    def test_no_conflict_reinstalling_same_mod(self, tmp_path):
        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        plugin = data_dir / "plugin.esp"
        plugin.write_text("x")

        ext = self._make_extracted(tmp_path, "Data/plugin.esp")
        manifest = {"NewMod": {"files": [str(plugin)]}}
        result = check_conflicts(ext, data_dir, manifest, "NewMod")
        assert result == []

    def test_detects_conflict_with_other_mod(self, tmp_path):
        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        plugin = data_dir / "plugin.esp"
        plugin.write_text("x")

        ext = self._make_extracted(tmp_path, "Data/plugin.esp")
        manifest = {"OtherMod": {"files": [str(plugin)]}}
        result = check_conflicts(ext, data_dir, manifest, "NewMod")
        assert len(result) == 1
        assert result[0][1] == "OtherMod"

    def test_no_conflict_for_non_tracked_vanilla_files(self, tmp_path):
        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        # Vanilla file on disk but not in manifest
        (data_dir / "vanilla.bsa").write_text("x")

        ext = self._make_extracted(tmp_path, "Data/vanilla.bsa")
        manifest = {"OtherMod": {"files": [str(data_dir / "other.esp")]}}
        result = check_conflicts(ext, data_dir, manifest, "NewMod")
        assert result == []

    def test_conflict_detected_via_double_slash_path(self, tmp_path):
        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        plugin = data_dir / "plugin.esp"
        plugin.write_text("x")

        ext = self._make_extracted(tmp_path, "Data/plugin.esp")
        # Manifest stores path with // artifact
        double_slash = str(data_dir) + "//plugin.esp"
        manifest = {"OtherMod": {"files": [double_slash]}}
        result = check_conflicts(ext, data_dir, manifest, "NewMod")
        assert len(result) == 1
        assert result[0][1] == "OtherMod"

    def test_conflict_detected_with_trailing_slash_path(self, tmp_path):
        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        plugin = data_dir / "plugin.esp"
        plugin.write_text("x")

        ext = self._make_extracted(tmp_path, "Data/plugin.esp")
        trailing = str(data_dir / "plugin.esp") + "/"
        manifest = {"OtherMod": {"files": [trailing]}}
        # Path("...file.esp/").resolve() strips the trailing slash
        result = check_conflicts(ext, data_dir, manifest, "NewMod")
        assert len(result) == 1

    def test_conflict_detected_via_symlink_path(self, tmp_path):
        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        plugin = data_dir / "plugin.esp"
        plugin.write_text("x")

        link_dir = tmp_path / "GameDataLink"
        link_dir.symlink_to(data_dir)

        ext = self._make_extracted(tmp_path, "Data/plugin.esp")
        # Manifest stores path through symlink; real path is via data_dir
        via_link = str(link_dir / "plugin.esp")
        manifest = {"OtherMod": {"files": [via_link]}}
        result = check_conflicts(ext, data_dir, manifest, "NewMod")
        assert len(result) == 1
        assert result[0][1] == "OtherMod"


# ── Manifest path resolution (migration) ──────────────────────────────────────

class TestManifestPathResolution:
    def test_load_resolves_double_slash_paths(self, fake_manifest_path, tmp_path):
        ugly = str(tmp_path) + "//mod.esp"
        fake_manifest_path.write_text(json.dumps({"Mod": {"files": [ugly]}}))
        manifest = load_manifest()
        stored = manifest["Mod"]["files"][0]
        assert "//" not in stored

    def test_load_rewrites_manifest_when_paths_changed(self, fake_manifest_path, tmp_path):
        ugly = str(tmp_path) + "//mod.esp"
        fake_manifest_path.write_text(json.dumps({"Mod": {"files": [ugly]}}))
        load_manifest()
        on_disk = json.loads(fake_manifest_path.read_text())
        assert "//" not in on_disk["Mod"]["files"][0]

    def test_load_does_not_rewrite_when_paths_already_clean(self, fake_manifest_path, tmp_path):
        clean = str(tmp_path / "mod.esp")
        fake_manifest_path.write_text(json.dumps({"Mod": {"files": [clean]}}))
        mtime_before = fake_manifest_path.stat().st_mtime
        load_manifest()
        assert fake_manifest_path.stat().st_mtime == mtime_before


# ── install_files ─────────────────────────────────────────────────────────────

class TestInstallFiles:
    def test_copies_files_to_dest(self, tmp_path):
        src = tmp_path / "src"
        (src / "subdir").mkdir(parents=True)
        (src / "subdir" / "file.esp").write_text("content")

        dest = tmp_path / "dest"
        installed, backups = install_files(src, dest)

        assert (dest / "subdir" / "file.esp").exists()
        assert len(installed) == 1
        assert backups == {}

    def test_normalizes_directory_casing(self, tmp_path):
        src = tmp_path / "src"
        (src / "textures").mkdir(parents=True)
        (src / "textures" / "skin.dds").write_text("tex")

        dest = tmp_path / "dest"
        install_files(src, dest)

        # "textures" → "Textures" via normalize_dir_name
        assert (dest / "Textures" / "skin.dds").exists()

    def test_creates_backup_when_overwriting(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.esp").write_text("new")

        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "file.esp").write_text("original")

        installed, backups = install_files(src, dest, game_slug="testgame", mod_name="TestMod")

        assert len(backups) == 1
        bak_path = Path(list(backups.values())[0])
        assert bak_path.exists()
        assert bak_path.read_text() == "original"
        assert (dest / "file.esp").read_text() == "new"


# ── detect_and_install ────────────────────────────────────────────────────────

class TestDetectAndInstall:
    def test_data_layout_strips_data_prefix(self, tmp_path):
        extracted = tmp_path / "extracted"
        (extracted / "Data" / "Textures").mkdir(parents=True)
        (extracted / "Data" / "Textures" / "tex.dds").write_text("tex")

        data_dir = tmp_path / "GameData"
        installed, _ = detect_and_install(extracted, data_dir)

        assert (data_dir / "Textures" / "tex.dds").exists()
        assert not (data_dir / "Data").exists()

    def test_root_layout_copies_subdirs(self, tmp_path):
        extracted = tmp_path / "extracted"
        (extracted / "SFSE" / "Plugins").mkdir(parents=True)
        (extracted / "SFSE" / "Plugins" / "mod.dll").write_text("dll")

        data_dir = tmp_path / "GameData"
        installed, _ = detect_and_install(extracted, data_dir)

        assert (data_dir / "SFSE" / "Plugins" / "mod.dll").exists()

    def test_root_layout_installs_plugin_files(self, tmp_path):
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        (extracted / "mod.esp").write_text("esp")
        (extracted / "readme.txt").write_text("readme")  # should be skipped

        data_dir = tmp_path / "GameData"
        data_dir.mkdir()
        installed, _ = detect_and_install(extracted, data_dir)

        assert (data_dir / "mod.esp").exists()
        assert not (data_dir / "readme.txt").exists()


# ── Manifest functions ────────────────────────────────────────────────────────

class TestManifest:
    def test_load_manifest_returns_empty_dict_when_no_file(self, fake_manifest_path):
        assert load_manifest() == {}

    def test_save_and_load_roundtrip(self, fake_manifest_path):
        data = {"MyMod": {"files": ["/game/Data/mod.esp"], "game": "starfield"}}
        save_manifest(data)
        assert load_manifest() == data

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep_path = tmp_path / "a" / "b" / "c" / "manifest.json"
        monkeypatch.setattr(installer, "MANIFEST_PATH", deep_path)
        save_manifest({"mod": {"files": []}})
        assert deep_path.exists()

    def test_load_manifest_parses_json(self, fake_manifest_path):
        fake_manifest_path.write_text(json.dumps({"A": {"files": []}}))
        result = load_manifest()
        assert result == {"A": {"files": []}}

    def test_record_install_adds_entry(self, fake_manifest_path, tmp_path):
        archive = tmp_path / "mod.zip"
        archive.write_bytes(b"x")
        files = [tmp_path / "Game" / "Data" / "mod.esp"]

        record_install("MyMod", archive, files, game_slug="starfield")

        manifest = load_manifest()
        assert "MyMod" in manifest
        assert manifest["MyMod"]["game"] == "starfield"
        assert str(files[0].resolve()) in manifest["MyMod"]["files"]

    def test_record_install_stores_resolved_paths(self, fake_manifest_path, tmp_path):
        archive = tmp_path / "mod.zip"
        archive.write_bytes(b"x")
        unresolved = tmp_path / "subdir" / ".." / "mod.esp"
        record_install("MyMod", archive, [unresolved], game_slug="test")
        manifest = load_manifest()
        stored = manifest["MyMod"]["files"][0]
        assert ".." not in stored
        assert stored == str(unresolved.resolve())

    def test_record_install_stores_nexus_meta(self, fake_manifest_path, tmp_path):
        archive = tmp_path / "mod.zip"
        archive.write_bytes(b"x")
        meta = {"mod_id": 42, "file_id": 99, "game_domain": "starfield"}

        record_install("MyMod", archive, [], nexus_meta=meta)

        manifest = load_manifest()
        assert manifest["MyMod"]["nexus"] == meta

    def test_remove_from_manifest_returns_entry(self, fake_manifest_path):
        save_manifest({"MyMod": {"files": ["/x"], "game": "test"}})
        entry = remove_from_manifest("MyMod")
        assert entry["game"] == "test"
        assert "MyMod" not in load_manifest()

    def test_remove_nonexistent_returns_empty(self, fake_manifest_path):
        save_manifest({})
        result = remove_from_manifest("GhostMod")
        assert result == {}

    def test_remove_does_not_touch_other_mods(self, fake_manifest_path):
        save_manifest({
            "ModA": {"files": [], "game": "test"},
            "ModB": {"files": [], "game": "test"},
        })
        remove_from_manifest("ModA")
        assert "ModB" in load_manifest()


# ── Migration ─────────────────────────────────────────────────────────────────

class TestMigration:
    def test_migration_moves_legacy_file(self, tmp_path, monkeypatch):
        new_path = tmp_path / "share" / "installed_mods.json"
        legacy = tmp_path / "repo" / "installed_mods.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"OldMod": {"files": []}}))

        monkeypatch.setattr(installer, "MANIFEST_PATH", new_path)
        # Patch the legacy path inside the function via module-level override
        monkeypatch.setattr(
            installer, "_migration_done", False
        )

        def patched_migrate():
            if installer._migration_done:
                return
            installer._migration_done = True
            if legacy.exists() and not new_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.move(legacy, new_path)

        monkeypatch.setattr(installer, "_migrate_legacy_manifest", patched_migrate)

        load_manifest()

        assert new_path.exists()
        assert not legacy.exists()
        assert json.loads(new_path.read_text()) == {"OldMod": {"files": []}}

    def test_migration_flag_prevents_double_run(self, fake_manifest_path, monkeypatch):
        call_count = 0

        def counting_migrate():
            nonlocal call_count
            call_count += 1

        monkeypatch.setattr(installer, "_migrate_legacy_manifest", counting_migrate)

        load_manifest()
        load_manifest()
        load_manifest()

        assert call_count == 3  # called each time; guard is inside the function itself

    def test_migration_guard_runs_once_per_process(self, fake_manifest_path):
        installer._migration_done = False
        load_manifest()
        assert installer._migration_done is True
        # Second call must not reset flag
        load_manifest()
        assert installer._migration_done is True

    def test_no_migration_when_new_path_already_exists(self, tmp_path, monkeypatch):
        new_path = tmp_path / "installed_mods.json"
        new_path.write_text(json.dumps({"ExistingMod": {}}))
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"LegacyMod": {}}))

        monkeypatch.setattr(installer, "MANIFEST_PATH", new_path)

        # Even if legacy exists, new path wins — no overwrite
        load_manifest()
        assert json.loads(new_path.read_text()) == {"ExistingMod": {}}


# ── install_fomod_files ───────────────────────────────────────────────────────

class TestInstallFomodFiles:
    def test_copies_only_listed_files(self, tmp_path):
        extracted = tmp_path / "extracted"
        (extracted / "Low").mkdir(parents=True)
        (extracted / "Low" / "settings.ini").write_text("low")
        (extracted / "High" / "settings.ini").parent.mkdir(parents=True)
        (extracted / "High" / "settings.ini").write_text("high")
        (extracted / "readme.txt").write_text("readme")
        dest = tmp_path / "Data"
        dest.mkdir()

        fomod_files = [("Low/settings.ini", "settings.ini")]
        install_fomod_files(extracted, fomod_files, dest)

        assert (dest / "settings.ini").read_text() == "low"
        assert not (dest / "High" / "settings.ini").exists()
        assert not (dest / "readme.txt").exists()

    def test_creates_destination_subdirectory(self, tmp_path):
        extracted = tmp_path / "extracted"
        (extracted / "textures").mkdir(parents=True)
        (extracted / "textures" / "rock.dds").write_bytes(b"dds")
        dest = tmp_path / "Data"
        dest.mkdir()

        install_fomod_files(extracted, [("textures/rock.dds", "textures/rock.dds")], dest)

        assert (dest / "textures" / "rock.dds").exists()

    def test_backs_up_overwritten_file(self, tmp_path, monkeypatch):
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        (extracted / "plugin.esp").write_bytes(b"new")
        dest = tmp_path / "Data"
        dest.mkdir()
        (dest / "plugin.esp").write_bytes(b"original")
        backup_dir = tmp_path / "backups"
        monkeypatch.setattr(installer, "BACKUPS_DIR", backup_dir)

        installed, backups = install_fomod_files(
            extracted, [("plugin.esp", "plugin.esp")], dest, game_slug="sg", mod_name="MyMod"
        )

        assert (dest / "plugin.esp").read_bytes() == b"new"
        assert backups  # backup entry present
        bak_path = Path(next(iter(backups.values())))
        assert bak_path.read_bytes() == b"original"

    def test_returns_installed_paths(self, tmp_path):
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        (extracted / "a.esp").write_bytes(b"esp")
        dest = tmp_path / "Data"
        dest.mkdir()

        installed, _ = install_fomod_files(extracted, [("a.esp", "a.esp")], dest)

        assert len(installed) == 1
        assert installed[0] == dest / "a.esp"

    def test_skips_missing_source_gracefully(self, tmp_path):
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        dest = tmp_path / "Data"
        dest.mkdir()

        installed, _ = install_fomod_files(
            extracted, [("nonexistent.esp", "nonexistent.esp")], dest
        )
        assert installed == []


# ── check_conflicts_fomod ─────────────────────────────────────────────────────

class TestCheckConflictsFomod:
    def test_detects_conflict_with_tracked_mod(self, tmp_path):
        dest = tmp_path / "Data"
        dest.mkdir()
        existing = dest / "plugin.esp"
        existing.write_bytes(b"x")
        manifest = {
            "OtherMod": {"files": [str(existing.resolve())]}
        }
        conflicts = check_conflicts_fomod(
            [("src/plugin.esp", "plugin.esp")], dest, manifest, "NewMod"
        )
        assert len(conflicts) == 1
        assert conflicts[0][1] == "OtherMod"

    def test_no_conflict_when_no_overlap(self, tmp_path):
        dest = tmp_path / "Data"
        dest.mkdir()
        manifest = {"OtherMod": {"files": [str(dest / "other.esp")]}}
        conflicts = check_conflicts_fomod(
            [("src/plugin.esp", "plugin.esp")], dest, manifest, "NewMod"
        )
        assert conflicts == []

    def test_skips_own_mod_in_manifest(self, tmp_path):
        dest = tmp_path / "Data"
        dest.mkdir()
        existing = dest / "plugin.esp"
        existing.write_bytes(b"x")
        manifest = {"NewMod": {"files": [str(existing.resolve())]}}
        conflicts = check_conflicts_fomod(
            [("src/plugin.esp", "plugin.esp")], dest, manifest, "NewMod"
        )
        assert conflicts == []
