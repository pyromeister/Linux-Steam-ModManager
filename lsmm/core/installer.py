"""
Generic archive extractor + file installer + manifest tracker.
Handles zip/7z/rar. Normalizes directory casing on Linux.
Tracks installed files in installed_mods.json for clean uninstall.
Caches mod archives and backs up overwritten files for safe restore.
"""

import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

import py7zr

from lsmm.core.config import normalize_dir_name, ARCHIVES_DIR, BACKUPS_DIR, MANIFEST_PATH

logger = logging.getLogger(__name__)

_migration_done = False


def _migrate_legacy_manifest() -> None:
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    legacy = Path(__file__).parent.parent.parent / "installed_mods.json"
    if legacy.exists() and not MANIFEST_PATH.exists():
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(legacy, MANIFEST_PATH)
        except OSError:
            pass  # migration failed; new path stays absent, caller gets empty manifest


# Extensions that need a Plugins.txt entry (Bethesda engine)
PLUGIN_EXTENSIONS = {".esp", ".esm", ".esl"}
DLL_EXTENSION = ".dll"


@contextmanager
def temp_extract_dir():
    tmp = Path(tempfile.mkdtemp(prefix="lsmm_"))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def safe_archive_member_path(dest: Path, member_name: str) -> Path:
    """Return member path inside dest, or raise if it would escape dest."""
    dest = dest.resolve()
    target = (dest / member_name).resolve()
    if not target.is_relative_to(dest):
        raise ValueError(f"Path traversal blocked: {member_name!r}")
    return target


def safe_extract_zip(z: zipfile.ZipFile, dest: Path) -> None:
    """Extract zip members only if they resolve inside dest (blocks path traversal)."""
    # Validate the whole archive first so a malicious later member cannot leave
    # earlier files partially extracted before the error is raised.
    for member in z.infolist():
        safe_archive_member_path(dest, member.filename)
    for member in z.infolist():
        z.extract(member, dest)


def extract(archive_path: Path, dest: Path) -> None:
    """Extract archive_path into dest directory. Supports zip, 7z, rar."""
    suffix = archive_path.suffix.lower()
    logger.debug("Extracting %s (format: %s) → %s", archive_path.name, suffix, dest)
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as z:
            safe_extract_zip(z, dest)
    elif suffix == ".7z":
        with py7zr.SevenZipFile(archive_path, mode='r') as z:
            names = z.getnames()
            for name in names:
                safe_archive_member_path(dest, name)
            z.extractall(path=dest)
    elif suffix == ".rar":
        result = subprocess.run(
            ["unrar", "x", "-y", str(archive_path), f"{dest}/"],
            capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors='replace') or result.stdout.decode(errors='replace')
            raise RuntimeError(f"unrar extraction failed: {err}")
    else:
        raise ValueError(f"Unsupported archive format: {suffix}")
    logger.debug("Extraction complete: %s", archive_path.name)


def detect_source_root(extracted: Path) -> tuple[Path, str, list]:
    """
    Detect the actual content root inside an extracted archive.
    Returns (root_path, layout_name, warnings).

    Layout names: "data" (content in Data/), "double" (Data/Data/), "root" (flat).
    Handles single wrapper folders transparently.
    """
    children = list(extracted.iterdir())

    if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        if inner.name.lower() == "data":
            double = inner / "Data"
            if double.is_dir():
                logger.debug("Layout detected: double (Data/Data/)")
                return double, "double", []
            logger.debug("Layout detected: data (Data/ at root)")
            return inner, "data", []
        # Wrapper folder — look for Data/ inside
        data_sub = inner / "Data"
        if data_sub.is_dir():
            double = data_sub / "Data"
            if double.is_dir():
                logger.debug("Layout detected: double via wrapper")
                return double, "double", []
            logger.debug("Layout detected: data via wrapper (%s/Data/)", inner.name)
            return data_sub, "data", []
        # Non-Data wrapper with no Data subfolder: copy wrapper + contents to dest
        logger.debug("Layout detected: root (flat, wrapper=%s)", inner.name)
        return extracted, "root", []

    logger.debug("Layout detected: root (flat, %d top-level items)", len(children))
    return extracted, "root", []


def _normalize_tree(src: Path) -> None:
    """
    Walk src recursively and rename any directories whose names have known
    wrong casing (e.g. 'interface' → 'Interface', 'sfse' → 'SFSE').
    Linux-only guard is inside normalize_dir_name().
    """
    # Process deepest paths first to avoid renaming a parent before its children
    dirs = sorted(
        [p for p in src.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for d in dirs:
        canonical = normalize_dir_name(d.name)
        if canonical and canonical != d.name:
            d.rename(d.parent / canonical)


def install_files(
    src_root: Path,
    dest_root: Path,
    game_slug: str | None = None,
    mod_name: str = "unknown",
) -> tuple[list[Path], dict[str, str]]:
    """
    Copy files from src_root into dest_root, normalizing directory casing.
    Returns (installed_files, backups) where backups maps dest→backup_path.
    """
    _normalize_tree(src_root)
    installed: list[Path] = []
    backups: dict[str, str] = {}

    backup_base = BACKUPS_DIR / (game_slug or "unknown") / mod_name
    logger.debug("Installing files: %s → %s", src_root, dest_root)

    for src_file in src_root.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_root)
        dst = dest_root / rel

        if _should_skip(src_file):
            logger.debug("Skipped: %s", rel)
            continue

        # Back up existing file before overwriting
        if dst.exists():
            bak = backup_base / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bak)
            backups[str(dst)] = str(bak)
            logger.debug("Backed up: %s → %s", dst, bak)

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        logger.debug("Installed: %s", rel)
        installed.append(dst)

    logger.debug("install_files done: %d files installed, %d backed up", len(installed), len(backups))
    return installed, backups


def detect_and_install(
    extracted: Path,
    dest_root: Path,
    game_slug: str | None = None,
    mod_name: str = "unknown",
) -> tuple[list[Path], dict[str, str]]:
    """Detect source root inside extracted archive, then install."""
    src_root, _, _ = detect_source_root(extracted)
    return install_files(src_root, dest_root, game_slug, mod_name)


def _should_skip(path: Path) -> bool:
    """Return True for files that should never be installed."""
    name_lower = path.name.lower()
    suffix_lower = path.suffix.lower()
    skip_names = {"readme.txt", "readme.md", "changelog.txt", "changelog.md",
                  "license.txt", "license.md", "credits.txt"}
    skip_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf", ".psd", ".nfo"}
    return name_lower in skip_names or suffix_lower in skip_suffixes


def cache_archive(archive_path: Path, game_slug: str | None) -> Path:
    """Copy archive to the LSMM cache directory. Returns the cached path."""
    dest_dir = ARCHIVES_DIR / (game_slug or "unknown")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / archive_path.name
    if dest != archive_path:
        shutil.copy2(archive_path, dest)
    return dest


def check_conflicts(
    extracted: Path,
    dest_root: Path,
    manifest: dict,
    installing_mod: str,
) -> list[tuple[str, str]]:
    """
    Return list of (filename, owner_mod) for files that would overwrite
    files owned by a different tracked mod.
    """
    # Build reverse index: resolved_path → mod_name
    file_to_mod: dict[str, str] = {}
    for mod_name, entry in manifest.items():
        if mod_name == installing_mod:
            continue
        for f in entry.get("files", []):
            try:
                key = str(Path(f).resolve(strict=False))
            except OSError:
                key = f
            file_to_mod[key] = mod_name

    src_root, _, _ = detect_source_root(extracted)
    conflicts = []
    for src_file in src_root.rglob("*"):
        if not src_file.is_file() or _should_skip(src_file):
            continue
        rel = src_file.relative_to(src_root)
        dst = dest_root / rel
        try:
            key = str(dst.resolve(strict=False))
        except OSError:
            key = str(dst)
        owner = file_to_mod.get(key)
        if owner:
            conflicts.append((str(rel), owner))

    return conflicts


# ── Manifest ─────────────────────────────────────────────────────────────────

def _resolve_manifest_paths(manifest: dict) -> tuple[dict, bool]:
    """Resolve all file paths in manifest entries. Returns (manifest, changed)."""
    changed = False
    for entry in manifest.values():
        files = entry.get("files", [])
        resolved = [str(Path(f).resolve(strict=False)) for f in files]
        if resolved != files:
            entry["files"] = resolved
            changed = True
    return manifest, changed


def load_manifest() -> dict:
    _migrate_legacy_manifest()
    if not MANIFEST_PATH.exists():
        return {}
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest, changed = _resolve_manifest_paths(manifest)
    if changed:
        save_manifest(manifest)
    return manifest


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
    staged: bool = False,
    staging_path: Path | None = None,
) -> None:
    manifest = load_manifest()
    entry: dict = {
        "archive": str(archive),
        "archive_cache": str(archive_cache) if archive_cache else None,
        "files": [str(f.resolve()) for f in installed_files],
        "game": game_slug,
        "backups": backups or {},
    }
    if nexus_meta:
        entry["nexus"] = nexus_meta
    if staged:
        entry["staged"] = True
        entry["staging_path"] = str(staging_path) if staging_path else None
    manifest[mod_name] = entry
    save_manifest(manifest)
    logger.debug("Recorded install: mod=%s game=%s files=%d", mod_name, game_slug, len(installed_files))


def remove_from_manifest(mod_name: str) -> dict:
    """Remove mod from manifest. Returns the removed entry dict (or {})."""
    manifest = load_manifest()
    entry = manifest.pop(mod_name, None)
    if entry:
        save_manifest(manifest)
        return entry
    return {}


def install_fomod_files(
    extracted: Path,
    fomod_files: list[tuple[str, str]],
    dest_root: Path,
    game_slug: str | None = None,
    mod_name: str = "unknown",
) -> tuple[list[Path], dict[str, str]]:
    """Copy specific (src, dst) pairs from extracted archive dir to dest_root."""
    installed: list[Path] = []
    backups: dict[str, str] = {}
    backup_base = BACKUPS_DIR / (game_slug or "unknown") / mod_name
    extracted_resolved = extracted.resolve()
    dest_resolved = dest_root.resolve()

    for src_rel, dst_rel in fomod_files:
        src_file = (extracted / src_rel).resolve()
        if not src_file.is_relative_to(extracted_resolved):
            raise ValueError(f"FOMOD path traversal blocked (src): {src_rel!r}")
        if not src_file.exists() or not src_file.is_file():
            continue
        if _should_skip(src_file):
            continue
        dst = (dest_root / dst_rel).resolve()
        if not dst.is_relative_to(dest_resolved):
            raise ValueError(f"FOMOD path traversal blocked (dst): {dst_rel!r}")

        if dst.exists():
            bak = backup_base / dst_rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bak)
            backups[str(dst)] = str(bak)

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        installed.append(dst)

    return installed, backups


def check_conflicts_fomod(
    fomod_files: list[tuple[str, str]],
    dest_root: Path,
    manifest: dict,
    installing_mod: str,
) -> list[tuple[str, str]]:
    """Check conflicts for a specific (src, dst) file list instead of a full extract tree."""
    file_to_mod: dict[str, str] = {}
    for mod_name, entry in manifest.items():
        if mod_name == installing_mod:
            continue
        for f in entry.get("files", []):
            try:
                key = str(Path(f).resolve(strict=False))
            except OSError:
                key = f
            file_to_mod[key] = mod_name

    dest_resolved = dest_root.resolve()
    conflicts = []
    for _, dst_rel in fomod_files:
        dst = (dest_root / dst_rel).resolve()
        if not dst.is_relative_to(dest_resolved):
            raise ValueError(f"FOMOD path traversal blocked (dst): {dst_rel!r}")
        try:
            key = str(dst.resolve(strict=False))
        except OSError:
            key = str(dst)
        owner = file_to_mod.get(key)
        if owner:
            conflicts.append((dst_rel, owner))
    return conflicts


class ConflictError(Exception):
    """Raised when installing a mod would overwrite files owned by another mod."""
    def __init__(self, conflicts: list[tuple[str, str]]):
        self.conflicts = conflicts
        lines = "\n".join(f"  {f} (owned by {o})" for f, o in conflicts)
        super().__init__(f"Conflicting files:\n{lines}")
