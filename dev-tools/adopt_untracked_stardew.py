#!/usr/bin/env python3
"""
One-time migration: adopt untracked Stardew Valley mods into LSMM staging.

For each real directory in Mods/ that is not yet staged:
  1. Copy folder → ~/.local/share/lsmm/staging/stardew_valley/<name>/
  2. Remove real directory from Mods/
  3. Deploy folder symlink if mod was active (no .disabled suffix)
  4. Write manifest entry

Skips:
  - Mods already in staging (idempotent)
  - SMAPI-internal mods (manifest.json UniqueID starts with "SMAPI.")
  - Mods already in the LSMM manifest

Usage:
  cd <lsmm-repo-root>
  python dev-tools/adopt_untracked_stardew.py [--dry-run]
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from lsmm.core.config import find_library_for_app
from lsmm.core.installer import load_manifest, save_manifest
from lsmm.core.staging import (
    deploy_mod_folder,
    get_mod_staging_dir,
    is_staged,
)

GAME_SLUG = "stardew_valley"
STEAM_APP_ID = "413150"


def _parse_smapi_manifest(path: Path) -> dict | None:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            raw = path.read_text(encoding=enc, errors="replace")
            raw = re.sub(r"//[^\n]*", "", raw)
            raw = re.sub(r",\s*([\}\]])", r"\1", raw)
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def _is_smapi_internal(mod_dir: Path) -> bool:
    manifest_path = mod_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    data = _parse_smapi_manifest(manifest_path)
    if not data:
        return False
    uid = next((v for k, v in data.items() if k.lower() == "uniqueid"), "")
    return str(uid).startswith("SMAPI.")


def adopt_untracked(mods_dir: Path, dry_run: bool) -> None:
    manifest = load_manifest()
    already_manifest = set(manifest.keys())

    skipped_internal = []
    skipped_staged = []
    skipped_manifest = []
    adopted = []
    errors = []

    entries = sorted(mods_dir.iterdir())
    for entry in entries:
        if not entry.is_dir():
            continue

        is_disabled = entry.name.endswith(".disabled")
        mod_name = entry.name.removesuffix(".disabled")
        is_active = not is_disabled

        # Skip if already in manifest
        if mod_name in already_manifest:
            skipped_manifest.append(mod_name)
            continue

        # Skip SMAPI-internal mods
        if _is_smapi_internal(entry):
            skipped_internal.append(mod_name)
            continue

        # Skip if already staged (idempotent)
        if is_staged(GAME_SLUG, mod_name):
            skipped_staged.append(mod_name)
            continue

        staging_dir = get_mod_staging_dir(GAME_SLUG, mod_name)

        print(f"  {'[DRY]' if dry_run else '      '} {mod_name!r}"
              f" {'(active)' if is_active else '(disabled)'}")

        if dry_run:
            adopted.append(mod_name)
            continue

        try:
            # 1. Copy to staging (clear any partial prior attempt first)
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            shutil.copytree(entry, staging_dir)

            # 2. Remove original dir from Mods/
            if entry.is_symlink():
                entry.unlink()
            else:
                shutil.rmtree(entry)

            # 3. Deploy symlink for active mods
            if is_active:
                deploy_mod_folder(GAME_SLUG, mod_name, mods_dir)
                installed = [
                    mods_dir / mod_name / f.relative_to(staging_dir)
                    for f in staging_dir.rglob("*")
                    if f.is_file()
                ]
            else:
                installed = []

            # 4. Write manifest entry directly (no original archive available)
            manifest[mod_name] = {
                "game": GAME_SLUG,
                "files": [str(p) for p in installed],
                "nexus": None,
                "adopted": True,
            }
            save_manifest(manifest)
            adopted.append(mod_name)

        except Exception as e:
            print(f"    ERROR adopting {mod_name!r}: {e}", file=sys.stderr)
            errors.append((mod_name, str(e)))
            # Clean up partial staging on error
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    print()
    print(f"Adopted:          {len(adopted)}")
    print(f"Skipped (manifest): {len(skipped_manifest)}")
    print(f"Skipped (staged):   {len(skipped_staged)}")
    print(f"Skipped (SMAPI.*):  {len(skipped_internal)}")
    if errors:
        print(f"Errors:           {len(errors)}")
        for name, msg in errors:
            print(f"  {name}: {msg}")
    if dry_run:
        print("\n(dry-run — no changes made)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be adopted without making changes")
    args = parser.parse_args()

    steam_lib = find_library_for_app(STEAM_APP_ID) or (Path.home() / ".local/share/Steam")
    mods_dir = steam_lib / "steamapps/common/Stardew Valley/Mods"

    if not mods_dir.exists():
        print(f"Mods directory not found: {mods_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Adopting untracked mods from: {mods_dir}")
    print(f"Staging root: {Path.home() / '.local/share/lsmm/staging' / GAME_SLUG}")
    print()

    adopt_untracked(mods_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
