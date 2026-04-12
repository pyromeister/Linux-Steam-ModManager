"""
Generic archive extractor + file installer + manifest tracker.
Handles zip/7z/rar. Normalizes directory casing on Linux.
Tracks installed files in installed_mods.json for clean uninstall.
"""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from config import normalize_dir_name

MANIFEST_PATH = Path(__file__).parent.parent / "installed_mods.json"

# Extensions that need a Plugins.txt entry (Bethesda engine)
PLUGIN_EXTENSIONS = {".esm", ".esp", ".esl"}
# DLL extension — used for root-level installs and SE plugin directories
DLL_EXTENSION = ".dll"


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


def install_files(src_root: Path, dest_root: Path) -> list[Path]:
    """
    Copy all files from src_root into dest_root with case normalization.
    Returns list of destination paths written.
    """
    installed = []
    for src_file in src_root.rglob("*"):
        if not src_file.is_file():
            continue
        dst = _normalized_dest(src_file, src_root, dest_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        installed.append(dst)
    return installed


def detect_and_install(extracted: Path, data_dir: Path) -> list[Path]:
    """
    Detect mod layout, map to correct destination under data_dir, install.

    Handles:
      - Data/ at root             → strip Data/, copy to data_dir/
      - Data/Data/ (double nest)  → strip both, copy to data_dir/
      - SFSE/ at root             → copy to data_dir/SFSE/
      - Interface/ at root        → copy to data_dir/Interface/
      - *.esm/.esp/.esl at root   → copy to data_dir/
      - Mixed root                → each top-level dir/file handled individually
    """
    content_root, layout, tops = detect_source_root(extracted)

    if layout in ("data", "double"):
        # Standard: everything under content_root goes into data_dir/
        return install_files(content_root, data_dir)

    # Root-layout: handle each top-level entry
    installed = []

    for name_lower, src_path in tops.items():
        # Known subdirectory → map to correct location under data_dir
        if src_path.is_dir():
            canonical = normalize_dir_name(src_path.name)
            dest = data_dir / canonical
            installed.extend(install_files(src_path, dest))
        elif src_path.is_file():
            # Root-level files: only copy plugin files and known assets
            ext = src_path.suffix.lower()
            if ext in PLUGIN_EXTENSIONS or ext in {".dll", ".pdb"}:
                dst = data_dir / src_path.name
                shutil.copy2(src_path, dst)
                installed.append(dst)
            # Skip: readme, docs, images, etc.

    return installed


# ── Manifest ─────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def record_install(mod_name: str, archive: Path, installed_files: list[Path], game_slug: str | None = None) -> None:
    manifest = load_manifest()
    manifest[mod_name] = {
        "archive": str(archive),
        "files": [str(f) for f in installed_files],
        "game": game_slug,
    }
    save_manifest(manifest)


def remove_from_manifest(mod_name: str) -> list[Path]:
    """Remove mod from manifest. Returns list of files that were tracked."""
    manifest = load_manifest()
    entry = manifest.pop(mod_name, None)
    if entry:
        save_manifest(manifest)
        return [Path(f) for f in entry.get("files", [])]
    return []
