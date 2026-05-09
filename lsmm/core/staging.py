"""
Staging directory system.

Mods are extracted to ~/.local/share/lsmm/staging/<game>/<mod>/ instead of
directly into the game folder. deploy_mod() symlinks (or copies) staged files
into dest_root; undeploy_mod() reverses that.
"""

import os
import shutil
from pathlib import Path

from lsmm.core.installer import detect_source_root, extract

STAGING_ROOT = Path.home() / ".local/share/lsmm/staging"


def get_staging_dir(game_slug: str) -> Path:
    return STAGING_ROOT / game_slug


def get_mod_staging_dir(game_slug: str, mod_name: str) -> Path:
    return STAGING_ROOT / game_slug / mod_name


def stage_mod(
    archive_path: Path,
    game_slug: str,
    mod_name: str,
) -> list[Path]:
    """Extract archive into staging dir. Returns list of relative paths."""
    import tempfile

    staging_dir = get_mod_staging_dir(game_slug, mod_name)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lsmm_stage_") as tmp:
        tmp_path = Path(tmp)
        extract(archive_path, tmp_path)
        src_root, _, _ = detect_source_root(tmp_path)
        rel_paths: list[Path] = []
        for src_file in src_root.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(src_root)
            dst = staging_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)
            rel_paths.append(rel)

    return rel_paths


def is_staged(game_slug: str, mod_name: str) -> bool:
    staging_dir = get_mod_staging_dir(game_slug, mod_name)
    if not staging_dir.exists():
        return False
    return any(staging_dir.rglob("*"))


def staged_files(game_slug: str, mod_name: str) -> list[Path]:
    """Return relative paths of all files in the staging dir."""
    staging_dir = get_mod_staging_dir(game_slug, mod_name)
    if not staging_dir.exists():
        return []
    return [
        f.relative_to(staging_dir)
        for f in staging_dir.rglob("*")
        if f.is_file()
    ]


def deploy_mod(game_slug: str, mod_name: str, dest_root: Path) -> list[Path]:
    """
    Symlink staged files into dest_root.
    Falls back to copy per-file when os.symlink raises OSError (cross-filesystem).
    Returns list of deployed destination paths.
    """
    staging_dir = get_mod_staging_dir(game_slug, mod_name)
    deployed: list[Path] = []
    for rel in staged_files(game_slug, mod_name):
        src = (staging_dir / rel).resolve()
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        try:
            os.symlink(src, dst)
        except OSError:
            shutil.copy2(src, dst)
        deployed.append(dst)
    return deployed


def undeploy_mod(game_slug: str, mod_name: str, dest_root: Path) -> None:
    """
    Remove only symlinks in dest_root that point into this mod's staging dir.
    Does NOT touch plain files or symlinks to other locations.
    """
    staging_dir = get_mod_staging_dir(game_slug, mod_name).resolve()
    for rel in staged_files(game_slug, mod_name):
        dst = dest_root / rel
        if not dst.is_symlink():
            continue
        try:
            target = dst.resolve()
        except OSError:
            target = Path(os.readlink(dst)).resolve()
        if target.is_relative_to(staging_dir):
            dst.unlink()
            try:
                dst.parent.rmdir()
            except OSError:
                pass  # not empty — leave it


def remove_staged_mod(game_slug: str, mod_name: str) -> None:
    """Delete the entire staging directory for a mod."""
    staging_dir = get_mod_staging_dir(game_slug, mod_name)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
