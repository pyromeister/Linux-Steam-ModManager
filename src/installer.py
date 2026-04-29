"""
Generic archive extractor + file installer + manifest tracker.
Handles zip/7z/rar. Normalizes directory casing on Linux.
Tracks installed files in installed_mods.json for clean uninstall.
Caches mod archives and backs up overwritten files for safe restore.
"""

import json
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from config import normalize_dir_name, ARCHIVES_DIR, BACKUPS_DIR, MANIFEST_PATH

_migration_done = False


def _migrate_legacy_manifest() -> None:
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    legacy = Path(__file__).parent.parent / "installed_mods.json"
    if legacy.exists() and not MANIFEST_PATH.exists():
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(legacy, MANIFEST_PATH)
        except OSError:
            pass  # migration failed; new path stays absent, caller gets empty manifest


# Extensions that need a Plugins.txt entry (Bethesda engine)
PLUGIN_EXTENSIONS = {".esm", ".esp", ".esl"}
# DLL extension — used for root-level installs and SE plugin directories
DLL_EXTENSION = ".dll"


class ConflictError(Exception):
    """Raised when a mod install would overwrite files owned by another tracked mod."""
    def __init__(self, conflicts: list[tuple[str, str]]):
        # conflicts: [(relative_path, owning_mod_name), ...]
        self.conflicts = conflicts
        super().__init__(f"{len(conflicts)} file conflict(s)")


# ── Temp extraction directory ─────────────────────────────────────────────────

@contextmanager
def temp_extract_dir():
    tmp = Path(tempfile.mkdtemp(prefix="lsmm_"))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Archive extraction ────────────────────────────────────────────────────────

def extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    elif suffix == ".7z":
        subprocess.run(
            ["7z", "x", str(archive), f"-o{dest}", "-y", "-bso0"],
            check=True,
        )
    elif suffix == ".rar":
        subprocess.run(
            ["unrar", "x", "-y", str(archive), str(dest) + "/"],
            check=True,
        )
    else:
        raise ValueError(f"Unsupported archive format: {suffix}")


# ── Archive cache ─────────────────────────────────────────────────────────────

def cache_archive(archive: Path, game_slug: str) -> Path:
    """
    Copy archive to the managed archives directory.
    Skips the copy if the destination already exists (same name).
    Returns the cached archive path.
    """
    dest_dir = ARCHIVES_DIR / game_slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / archive.name
    if not dest.exists():
        shutil.copy2(archive, dest)
    return dest


# ── Directory structure detection ────────────────────────────────────────────

def _top_names(root: Path) -> dict[str, Path]:
    """Map lowercase name → actual Path for direct children of root."""
    return {p.name.lower(): p for p in root.iterdir()}


def detect_source_root(extracted: Path) -> tuple[Path, str, dict]:
    """
    Detect where the actual mod content starts in an extracted archive.

    Returns (content_root, layout_type, tops) where:
      layout_type is 'data', 'double', or 'root'
      tops is _top_names(content_root) — pre-computed to avoid double scan
    """
    tops = _top_names(extracted)

    # Double-nesting: Data/Data/ — Vortex-managed mods sometimes do this
    if "data" in tops:
        inner = _top_names(tops["data"])
        if "data" in inner:
            content_root = inner["data"]
            return content_root, "double", _top_names(content_root)
        return tops["data"], "data", inner

    # Single wrapper directory containing Data/ (e.g. ModName/Data/plugin.esp)
    if len(tops) == 1:
        only = next(iter(tops.values()))
        if only.is_dir():
            inner = _top_names(only)
            if "data" in inner:
                sub_inner = _top_names(inner["data"])
                if "data" in sub_inner:
                    content_root = sub_inner["data"]
                    return content_root, "double", _top_names(content_root)
                return inner["data"], "data", sub_inner

    return extracted, "root", tops


# ── Conflict detection ────────────────────────────────────────────────────────

def check_conflicts(
    extracted: Path,
    data_dir: Path,
    manifest: dict,
    new_mod_name: str,
) -> list[tuple[str, str]]:
    """
    Scan what a mod would install and find files already owned by other mods.
    Returns [(relative_path_under_data_dir, owning_mod_name), ...].
    Vanilla files (present on disk but not in any manifest) are NOT reported.
    """
    # Reverse index: absolute path string → owning mod name
    file_to_mod: dict[str, str] = {}
    for mod_name, entry in manifest.items():
        if mod_name == new_mod_name:
            continue  # reinstalling same mod is not a conflict
        for f in entry.get("files", []):
            file_to_mod[f] = mod_name

    if not file_to_mod:
        return []

    content_root, layout, tops = detect_source_root(extracted)
    conflicts: list[tuple[str, str]] = []

    def _scan(src_root: Path, dst_root: Path) -> None:
        for src_file in src_root.rglob("*"):
            if not src_file.is_file():
                continue
            dst = _normalized_dest(src_file, src_root, dst_root)
            owner = file_to_mod.get(str(dst))
            if owner:
                try:
                    rel = str(dst.relative_to(data_dir))
                except ValueError:
                    rel = str(dst)
                conflicts.append((rel, owner))

    if layout in ("data", "double"):
        _scan(content_root, data_dir)
    else:
        for _name_lower, src_path in tops.items():
            if src_path.is_dir():
                canonical = normalize_dir_name(src_path.name)
                _scan(src_path, data_dir / canonical)
            elif src_path.is_file():
                ext = src_path.suffix.lower()
                if ext in PLUGIN_EXTENSIONS or ext in {".dll", ".pdb"}:
                    dst = data_dir / src_path.name
                    owner = file_to_mod.get(str(dst))
                    if owner:
                        conflicts.append((src_path.name, owner))

    return conflicts


# ── File copy with case normalization ────────────────────────────────────────

def _normalized_dest(src_file: Path, src_root: Path, dest_root: Path) -> Path:
    """
    Build destination path, normalizing each directory component's casing.
    src_file is a file under src_root. dest_root is the game's Data/ dir.
    """
    rel = src_file.relative_to(src_root)
    parts = list(rel.parts)

    # Normalize each directory component (not the filename itself)
    normalized = []
    for part in parts[:-1]:
        normalized.append(normalize_dir_name(part))
    normalized.append(parts[-1])  # filename unchanged

    return dest_root.joinpath(*normalized)


def _backup_file(dst: Path, dest_root: Path, game_slug: str, mod_name: str) -> Path:
    """
    Back up an existing file before it is overwritten.
    Stores in BACKUPS_DIR/game_slug/mod_name/<relative_to_dest_root>.
    Returns the backup path.
    """
    rel = dst.relative_to(dest_root)
    backup = BACKUPS_DIR / game_slug / mod_name / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dst, backup)
    return backup


def install_files(
    src_root: Path,
    dest_root: Path,
    game_slug: str | None = None,
    mod_name: str | None = None,
) -> tuple[list[Path], dict[str, str]]:
    """
    Copy all files from src_root into dest_root with case normalization.
    If game_slug and mod_name are provided, backs up any file that would be
    overwritten before copying.
    Returns (installed_paths, backups) where backups maps dst → backup_path.
    """
    installed = []
    backups: dict[str, str] = {}
    for src_file in src_root.rglob("*"):
        if not src_file.is_file():
            continue
        dst = _normalized_dest(src_file, src_root, dest_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if game_slug and mod_name and dst.exists():
            bak = _backup_file(dst, dest_root, game_slug, mod_name)
            backups[str(dst)] = str(bak)
        shutil.copy2(src_file, dst)
        installed.append(dst)
    return installed, backups


def detect_and_install(
    extracted: Path,
    data_dir: Path,
    game_slug: str | None = None,
    mod_name: str | None = None,
) -> tuple[list[Path], dict[str, str]]:
    """
    Detect mod layout, map to correct destination under data_dir, install.
    Backs up overwritten files when game_slug and mod_name are given.
    Returns (installed_paths, backups).

    Handles:
      - Data/ at root             → strip Data/, copy to data_dir/
      - Data/Data/ (double nest)  → strip both, copy to data_dir/
      - ModName/Data/ (wrapper)   → strip wrapper + Data/, copy to data_dir/
      - SFSE/ at root             → copy to data_dir/SFSE/
      - Interface/ at root        → copy to data_dir/Interface/
      - *.esm/.esp/.esl at root   → copy to data_dir/
      - Mixed root                → each top-level dir/file handled individually
    """
    content_root, layout, tops = detect_source_root(extracted)

    if layout in ("data", "double"):
        return install_files(content_root, data_dir, game_slug, mod_name)

    # Root-layout: handle each top-level entry
    installed: list[Path] = []
    backups: dict[str, str] = {}

    for name_lower, src_path in tops.items():
        if src_path.is_dir():
            canonical = normalize_dir_name(src_path.name)
            dest = data_dir / canonical
            f, b = install_files(src_path, dest, game_slug, mod_name)
            installed.extend(f)
            backups.update(b)
        elif src_path.is_file():
            ext = src_path.suffix.lower()
            if ext in PLUGIN_EXTENSIONS or ext in {".dll", ".pdb"}:
                dst = data_dir / src_path.name
                if game_slug and mod_name and dst.exists():
                    bak = _backup_file(dst, data_dir, game_slug, mod_name)
                    backups[str(dst)] = str(bak)
                shutil.copy2(src_path, dst)
                installed.append(dst)
            # Skip: readme, docs, images, etc.

    return installed, backups


# ── Manifest ─────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    _migrate_legacy_manifest()
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def record_install(
    mod_name: str,
    archive: Path,
    installed_files: list[Path],
    game_slug: str | None = None,
    archive_cache: Path | None = None,
    backups: dict[str, str] | None = None,
    nexus_meta: dict | None = None,
) -> None:
    manifest = load_manifest()
    entry: dict = {
        "archive": str(archive),
        "archive_cache": str(archive_cache) if archive_cache else None,
        "files": [str(f) for f in installed_files],
        "game": game_slug,
        "backups": backups or {},
    }
    if nexus_meta:
        entry["nexus"] = nexus_meta
    manifest[mod_name] = entry
    save_manifest(manifest)


def remove_from_manifest(mod_name: str) -> dict:
    """Remove mod from manifest. Returns the removed entry dict (or {})."""
    manifest = load_manifest()
    entry = manifest.pop(mod_name, None)
    if entry:
        save_manifest(manifest)
        return entry
    return {}
