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

from lsmm.core.config import normalize_dir_name, ARCHIVES_DIR, BACKUPS_DIR, MANIFEST_PATH

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


def extract(archive_path: Path, dest: Path) -> None:
    """Extract archive_path into dest directory. Supports zip, 7z, rar."""
    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(dest)
    elif suffix in (".7z", ".rar"):
        result = subprocess.run(
            ["7z", "x", str(archive_path), f"-o{dest}", "-y"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"7z extraction failed: {result.stderr.decode(errors='replace')}"
            )
    else:
        raise ValueError(f"Unsupported archive format: {suffix}")


def detect_source_root(extracted: Path) -> Path:
    """
    Detect the actual content root inside an extracted archive.

    Handles four layouts:
      1. Data/plugin.esp at root → root is the source root
      2. ModName/Data/plugin.esp → ModName/ is a wrapper; skip it
      3. Data/Data/plugin.esp → double-nested; skip outer Data/
      4. plugin.esp at root → root is the source root (flat)
    """
    children = list(extracted.iterdir())

    # Single wrapper folder — go one level deeper
    if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        # Double-nest: Data/Data/… — skip the outer one
        if inner.name.lower() == "data" and (inner / "Data").exists():
            return inner
        # Otherwise the wrapper itself is the source root
        return inner

    return extracted


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
    game_slug: str | None,
    mod_name: str,
) -> tuple[list[Path], dict[str, str]]:
    """
    Copy files from src_root into dest_root, normalizing directory casing.
    Returns (installed_files, backups) where backups maps dest→backup_path.
    """
    _normalize_tree(src_root)
    installed: list[Path] = []
    backups: dict[str, str] = {}

    backup_base = BACKUPS_DIR / (game_slug or "unknown") / mod_name

    for src_file in src_root.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_root)
        dst = dest_root / rel

        if _should_skip(src_file):
            continue

        # Back up existing file before overwriting
        if dst.exists():
            bak = backup_base / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bak)
            backups[str(dst)] = str(bak)

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        installed.append(dst)

    return installed, backups


def detect_and_install(
    extracted: Path,
    dest_root: Path,
    game_slug: str | None,
    mod_name: str,
) -> tuple[list[Path], dict[str, str]]:
    """Detect source root inside extracted archive, then install."""
    src_root = detect_source_root(extracted)
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

    src_root = detect_source_root(extracted)
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


class ConflictError(Exception):
    """Raised when installing a mod would overwrite files owned by another mod."""
    def __init__(self, conflicts: list[tuple[str, str]]):
        self.conflicts = conflicts
        lines = "\n".join(f"  {f} (owned by {o})" for f, o in conflicts)
        super().__init__(f"Conflicting files:\n{lines}")
