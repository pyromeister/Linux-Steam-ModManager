"""Tests for BethesdaEngine.install() FOMOD integration (ISC-20 to ISC-25)."""

import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lsmm.core import installer
from lsmm.core.installer import ConflictError
from lsmm.engines.bethesda import BethesdaEngine

_PROFILE = {
    "name": "Starfield",
    "slug": "starfield",
    "steam_app_id": "1716740",
    "install_subdir": "Starfield",
    "engine": "bethesda",
    "game_exe": "Starfield.exe",
}


def _make_archive(tmp_path: Path, members: dict[str, bytes]) -> Path:
    arch = tmp_path / "mod.zip"
    with zipfile.ZipFile(arch, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    return arch


@pytest.fixture()
def eng(tmp_path, monkeypatch):
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    plugins_txt = tmp_path / "Plugins.txt"
    plugins_txt.write_text("")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")

    monkeypatch.setattr(installer, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(installer, "ARCHIVES_DIR", tmp_path / "archives")
    monkeypatch.setattr(installer, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(installer, "_migration_done", True)

    engine = BethesdaEngine(_PROFILE)
    engine.paths = SimpleNamespace(
        data_dir=data_dir,
        plugins_txt=plugins_txt,
        se_plugins_dir=None,
    )
    return engine


# ── ISC-20: fomod_files param accepted ───────────────────────────────────────

def test_install_accepts_fomod_files_kwarg(eng, tmp_path):
    arch = _make_archive(tmp_path, {"Low/settings.ini": b"low"})
    eng.install(arch, mod_name="TestMod", fomod_files=[("Low/settings.ini", "settings.ini")])
    assert (eng.paths.data_dir / "settings.ini").exists()


# ── ISC-21: detect_and_install NOT called when fomod_files given ──────────────

def test_install_with_fomod_files_skips_detect_and_install(eng, tmp_path):
    arch = _make_archive(tmp_path, {"Low/settings.ini": b"low"})
    with patch("lsmm.engines.bethesda.detect_and_install") as mock_dai:
        eng.install(arch, mod_name="TestMod", fomod_files=[("Low/settings.ini", "settings.ini")])
        mock_dai.assert_not_called()


# ── ISC-22: only listed files installed ──────────────────────────────────────

def test_install_with_fomod_files_only_copies_listed(eng, tmp_path):
    arch = _make_archive(tmp_path, {
        "Low/settings.ini": b"low",
        "High/settings.ini": b"high",
        "readme.txt": b"readme",
    })
    eng.install(arch, mod_name="TestMod", fomod_files=[("Low/settings.ini", "settings.ini")])
    assert (eng.paths.data_dir / "settings.ini").read_bytes() == b"low"
    assert not (eng.paths.data_dir / "High" / "settings.ini").exists()
    assert not (eng.paths.data_dir / "readme.txt").exists()


# ── ISC-23: conflict detection uses fomod_files ───────────────────────────────

def test_install_with_fomod_files_raises_conflict_error(eng, tmp_path, monkeypatch):
    existing = eng.paths.data_dir / "settings.ini"
    existing.write_bytes(b"owned")
    manifest_path = tmp_path / "manifest.json"
    import json
    manifest_path.write_text(json.dumps({
        "OtherMod": {"files": [str(existing.resolve())], "game": "starfield"}
    }))

    arch = _make_archive(tmp_path, {"Low/settings.ini": b"new"})
    with pytest.raises(ConflictError):
        eng.install(arch, mod_name="TestMod", fomod_files=[("Low/settings.ini", "settings.ini")])


# ── ISC-24: .esp from fomod dst registered in Plugins.txt ────────────────────

def test_install_with_fomod_files_registers_esp(eng, tmp_path):
    arch = _make_archive(tmp_path, {"plugin.esp": b"esp data"})
    eng.install(arch, mod_name="TestMod", fomod_files=[("plugin.esp", "plugin.esp")])
    plugins_txt = eng.paths.plugins_txt.read_text()
    assert "plugin.esp" in plugins_txt


# ── ISC-25: without fomod_files, normal path unchanged ───────────────────────

def test_install_without_fomod_files_uses_detect_and_install(eng, tmp_path):
    arch = _make_archive(tmp_path, {"Data/plugin.esp": b"esp data"})
    with patch("lsmm.engines.bethesda.detect_and_install", wraps=__import__(
        "lsmm.core.installer", fromlist=["detect_and_install"]
    ).detect_and_install) as mock_dai:
        eng.install(arch, mod_name="TestMod")
        mock_dai.assert_called_once()
