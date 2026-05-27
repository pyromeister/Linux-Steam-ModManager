"""Tests for manifest-consistency and dir-cleanup behavior in engine uninstall().

Issue #80: remove_from_manifest() must only run after successful file deletion.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from lsmm.core import installer
from lsmm.core.installer import load_manifest, record_install


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def fake_manifest(tmp_path, monkeypatch):
    path = tmp_path / "installed_mods.json"
    monkeypatch.setattr(installer, "MANIFEST_PATH", path)
    return path


def _bepinex_engine(tmp_path, monkeypatch):
    from lsmm.engines.bepinex import BepInExEngine
    monkeypatch.setattr("lsmm.engines.bepinex.find_library_for_app", lambda _: tmp_path)
    profile = {"steam_app_id": "0", "install_subdir": "game"}
    return BepInExEngine(profile)


def _modfolder_engine(tmp_path, monkeypatch):
    from lsmm.engines.modfolder import ModFolderEngine
    monkeypatch.setattr("lsmm.engines.modfolder.find_library_for_app", lambda _: tmp_path)
    profile = {
        "steam_app_id": "0",
        "install_subdir": "game",
        "mods_subdir": "Mods",
        "smapi": {"exe": "StardewModdingAPI"},
    }
    return ModFolderEngine(profile)


# ── Manifest preserved on delete failure (BepInEx) ───────────────────────────

def test_bepinex_manifest_preserved_on_delete_failure(tmp_path, fake_manifest, monkeypatch):
    engine = _bepinex_engine(tmp_path, monkeypatch)
    plugin_file = engine.plugins_dir / "MyMod" / "plugin.dll"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_bytes(b"dll")

    record_install("MyMod", plugin_file, [plugin_file], game_slug=None)
    assert "MyMod" in load_manifest()

    with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
        try:
            engine.uninstall("MyMod")
        except Exception:
            pass  # may propagate — what matters is manifest state

    assert "MyMod" in load_manifest(), "manifest entry must survive a failed delete"


# ── Manifest preserved on delete failure (ModFolder) ─────────────────────────

def test_modfolder_manifest_preserved_on_delete_failure(tmp_path, fake_manifest, monkeypatch):
    engine = _modfolder_engine(tmp_path, monkeypatch)
    mod_file = engine.mods_dir / "MyMod" / "about.xml"
    mod_file.parent.mkdir(parents=True, exist_ok=True)
    mod_file.write_bytes(b"xml")

    record_install("MyMod", mod_file, [mod_file], game_slug=None)
    assert "MyMod" in load_manifest()

    with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
        try:
            engine.uninstall("MyMod")
        except Exception:
            pass

    assert "MyMod" in load_manifest(), "manifest entry must survive a failed delete"


# ── Manifest removed on full success (BepInEx) ───────────────────────────────

def test_bepinex_manifest_removed_on_success(tmp_path, fake_manifest, monkeypatch):
    engine = _bepinex_engine(tmp_path, monkeypatch)
    plugin_file = engine.plugins_dir / "MyMod" / "plugin.dll"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_bytes(b"dll")

    record_install("MyMod", plugin_file, [plugin_file], game_slug=None)
    engine.uninstall("MyMod")

    assert "MyMod" not in load_manifest()


# ── Nested empty parent dirs cleaned up (BepInEx) ────────────────────────────

def test_bepinex_nested_empty_dirs_cleaned_on_uninstall(tmp_path, fake_manifest, monkeypatch):
    engine = _bepinex_engine(tmp_path, monkeypatch)
    # deep nested structure: plugins_dir/Author/ModName/v1/plugin.dll
    plugin_file = engine.plugins_dir / "Author" / "ModName" / "v1" / "plugin.dll"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_bytes(b"dll")

    record_install("DeepMod", plugin_file, [plugin_file], game_slug=None)
    engine.uninstall("DeepMod")

    assert not plugin_file.exists()
    assert not (engine.plugins_dir / "Author").exists(), "empty Author/ dir should be cleaned up"
