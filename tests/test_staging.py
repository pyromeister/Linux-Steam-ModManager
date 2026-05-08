"""Tests for the staging directory system (lsmm.core.staging)."""

import zipfile
from pathlib import Path

import pytest

from lsmm.core.staging import (
    STAGING_ROOT,
    deploy_mod,
    get_mod_staging_dir,
    get_staging_dir,
    is_staged,
    remove_staged_mod,
    stage_mod,
    staged_files,
    undeploy_mod,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_zip(dest: Path, files: dict[str, str]) -> Path:
    """Create a zip archive at dest containing the given {rel_path: content} files."""
    with zipfile.ZipFile(dest, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return dest


# ── ISC-26: stage_mod creates correct dir tree ───────────────────────────────

def test_stage_mod_creates_dir_tree(tmp_path, monkeypatch):
    monkeypatch.setattr("lsmm.core.staging.STAGING_ROOT", tmp_path / "staging")

    archive = _make_zip(tmp_path / "mod.zip", {
        "Data/Textures/foo.dds": "tex",
        "Data/meshes/bar.nif": "mesh",
    })

    rel_paths = stage_mod(archive, "starfield", "TestMod")

    staging_dir = tmp_path / "staging" / "starfield" / "TestMod"
    assert staging_dir.exists()
    names = {r.as_posix() for r in rel_paths}
    # detect_source_root strips the Data/ wrapper if present, so relative paths
    # are relative to the detected source root
    assert any("foo.dds" in n for n in names)
    assert any("bar.nif" in n for n in names)
    for rel in rel_paths:
        assert (staging_dir / rel).exists()


# ── ISC-27: deploy_mod + undeploy_mod roundtrip leaves no symlinks ────────────

def test_deploy_undeploy_roundtrip(tmp_path, monkeypatch):
    staging_root = tmp_path / "staging"
    monkeypatch.setattr("lsmm.core.staging.STAGING_ROOT", staging_root)

    # Manually populate staging dir
    staging_dir = staging_root / "skyrim" / "MyMod"
    (staging_dir / "Textures").mkdir(parents=True)
    (staging_dir / "Textures" / "test.dds").write_bytes(b"data")

    dest = tmp_path / "game" / "Data"
    dest.mkdir(parents=True)

    deployed = deploy_mod("skyrim", "MyMod", dest)
    assert len(deployed) == 1
    dst = deployed[0]
    assert dst.is_symlink()
    assert dst.resolve() == (staging_dir / "Textures" / "test.dds").resolve()

    undeploy_mod("skyrim", "MyMod", dest)
    assert not dst.exists()
    assert not dst.is_symlink()


# ── ISC-28: is_staged True after stage, False after remove_staged_mod ─────────

def test_is_staged_lifecycle(tmp_path, monkeypatch):
    staging_root = tmp_path / "staging"
    monkeypatch.setattr("lsmm.core.staging.STAGING_ROOT", staging_root)

    archive = _make_zip(tmp_path / "mod.zip", {"Data/file.esp": "plugin"})

    assert not is_staged("skyrimse", "Mod1")

    stage_mod(archive, "skyrimse", "Mod1")
    assert is_staged("skyrimse", "Mod1")

    remove_staged_mod("skyrimse", "Mod1")
    assert not is_staged("skyrimse", "Mod1")


# ── ISC-29: undeploy_mod only removes symlinks pointing into this mod's staging dir

def test_undeploy_ignores_foreign_symlinks(tmp_path, monkeypatch):
    staging_root = tmp_path / "staging"
    monkeypatch.setattr("lsmm.core.staging.STAGING_ROOT", staging_root)

    staging_dir = staging_root / "fo4" / "ModA"
    (staging_dir / "Textures").mkdir(parents=True)
    staged_file = staging_dir / "Textures" / "real.dds"
    staged_file.write_bytes(b"staged")

    dest = tmp_path / "game" / "Data"
    dest.mkdir(parents=True)

    # Deploy ModA
    deploy_mod("fo4", "ModA", dest)

    # Plant a foreign symlink that should NOT be removed
    other_target = tmp_path / "other.dds"
    other_target.write_bytes(b"other")
    foreign_link = dest / "Textures" / "foreign.dds"
    foreign_link.parent.mkdir(parents=True, exist_ok=True)
    foreign_link.symlink_to(other_target)

    undeploy_mod("fo4", "ModA", dest)

    # ModA's symlink gone
    assert not (dest / "Textures" / "real.dds").exists()
    # Foreign symlink untouched
    assert foreign_link.is_symlink()
    assert foreign_link.resolve() == other_target.resolve()


# ── staged_files returns relative paths ──────────────────────────────────────

def test_staged_files_returns_relative(tmp_path, monkeypatch):
    staging_root = tmp_path / "staging"
    monkeypatch.setattr("lsmm.core.staging.STAGING_ROOT", staging_root)

    staging_dir = staging_root / "game" / "Mod"
    (staging_dir / "sub").mkdir(parents=True)
    (staging_dir / "sub" / "a.txt").write_text("x")
    (staging_dir / "b.txt").write_text("y")

    rels = staged_files("game", "Mod")
    assert set(rels) == {Path("sub/a.txt"), Path("b.txt")}


# ── get_staging_dir / get_mod_staging_dir ────────────────────────────────────

def test_path_helpers(monkeypatch, tmp_path):
    root = tmp_path / "staging"
    monkeypatch.setattr("lsmm.core.staging.STAGING_ROOT", root)
    assert get_staging_dir("mygame") == root / "mygame"
    assert get_mod_staging_dir("mygame", "mod") == root / "mygame" / "mod"
