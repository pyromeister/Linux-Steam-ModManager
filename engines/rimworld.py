"""
RimWorld engine plugin.
Mods live in <game_root>/Mods/<PackageId>/
Load order + activation tracked in ModsConfig.xml (Unity config dir).
Capabilities: install/uninstall, activation toggle, load order.
"""

import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base import BaseEngine
from config import find_library_for_app
from installer import (
    ConflictError,
    cache_archive,
    extract,
    load_manifest,
    record_install,
    remove_from_manifest,
)

MODSCONFIG_PATH = (
    Path.home()
    / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml"
)


def _read_modsconfig() -> tuple[ET.ElementTree, ET.Element]:
    """Parse ModsConfig.xml. Returns (tree, activeMods element)."""
    if not MODSCONFIG_PATH.exists():
        raise FileNotFoundError(f"ModsConfig.xml not found: {MODSCONFIG_PATH}")
    tree = ET.parse(MODSCONFIG_PATH)
    root = tree.getroot()
    active_mods = root.find("activeMods")
    if active_mods is None:
        active_mods = ET.SubElement(root, "activeMods")
    return tree, active_mods


def _write_modsconfig(tree: ET.ElementTree) -> None:
    ET.indent(tree, space="  ")
    tree.write(MODSCONFIG_PATH, encoding="utf-8", xml_declaration=True)


def _get_active_package_ids() -> list[str]:
    """Return ordered list of active packageIds from ModsConfig.xml."""
    if not MODSCONFIG_PATH.exists():
        return []
    _, active_mods = _read_modsconfig()
    return [li.text.strip() for li in active_mods.findall("li") if li.text]


def _read_about(mod_dir: Path) -> dict:
    """Read About/About.xml from a mod folder. Returns {packageId, name}."""
    about = mod_dir / "About" / "About.xml"
    if not about.exists():
        return {"packageId": mod_dir.name.lower(), "name": mod_dir.name}
    try:
        root = ET.parse(about).getroot()
        pkg = root.findtext("packageId") or mod_dir.name.lower()
        name = root.findtext("name") or mod_dir.name
        return {"packageId": pkg.strip().lower(), "name": name.strip()}
    except ET.ParseError:
        return {"packageId": mod_dir.name.lower(), "name": mod_dir.name}


class RimWorldEngine(BaseEngine):
    has_load_order = True
    has_script_extender = False
    has_activation_toggle = True

    def __init__(self, profile: dict):
        super().__init__(profile)
        app_id = profile["steam_app_id"]
        subdir = profile["install_subdir"]
        steam_lib = find_library_for_app(app_id) or (Path.home() / ".local/share/Steam")
        self.game_root = steam_lib / "steamapps/common" / subdir
        self.mods_dir = self.game_root / "Mods"

    def _game_slug(self) -> str:
        return self.profile.get("slug", "rimworld")

    # ── Install ───────────────────────────────────────────────────────────────

    def install(
        self,
        archive_path: Path,
        mod_name: str = None,
        force: bool = False,
        nexus_meta: dict | None = None,
    ) -> None:
        """
        Extract archive into game_root/Mods/.
        Detects mod folder (looks for About/About.xml one level deep).
        Adds the mod's packageId to ModsConfig.xml activeMods.
        """
        name = mod_name or archive_path.stem
        game_slug = self._game_slug()
        tmp = Path(f"/tmp/linuxmm_rw_{name}")

        try:
            extract(archive_path, tmp)

            # Find the actual mod root: either tmp itself or one subfolder inside
            mod_root = self._find_mod_root(tmp)

            about = _read_about(mod_root)
            package_id = about["packageId"]
            display_name = about["name"]

            dest = self.mods_dir / mod_root.name
            if dest.exists() and not force:
                manifest = load_manifest()
                if name in manifest:
                    raise ConflictError([(mod_root.name, name)])

            archive_cache = cache_archive(archive_path, game_slug)
            self.mods_dir.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(mod_root, dest)

            installed_files = [f for f in dest.rglob("*") if f.is_file()]
            record_install(
                name,
                archive_path,
                installed_files,
                game_slug=game_slug,
                archive_cache=archive_cache,
                nexus_meta=nexus_meta,
            )

            self._activate_package(package_id)
            print(f"✓ Installed: {display_name} ({package_id})")

        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _find_mod_root(self, extracted: Path) -> Path:
        """
        Find the mod root directory inside an extracted archive.
        If the archive root contains About/About.xml → use it directly.
        If there's exactly one subfolder containing About/ → use that subfolder.
        Otherwise fall back to extracted root.
        """
        if (extracted / "About" / "About.xml").exists():
            return extracted
        candidates = [p for p in extracted.iterdir() if p.is_dir()]
        if len(candidates) == 1 and (candidates[0] / "About" / "About.xml").exists():
            return candidates[0]
        return extracted

    # ── Uninstall ─────────────────────────────────────────────────────────────

    def uninstall(self, mod_name: str) -> None:
        entry = remove_from_manifest(mod_name)
        if not entry:
            print(f"Not tracked: {mod_name}")
            return

        # Remove mod folder — find it by checking which Mods/ subdir owns the files
        deleted_dirs: set[Path] = set()
        for f_str in entry.get("files", []):
            f = Path(f_str)
            if f.exists():
                f.unlink()
            # Collect the top-level subdir under mods_dir
            try:
                rel = f.relative_to(self.mods_dir)
                top = self.mods_dir / rel.parts[0]
                deleted_dirs.add(top)
            except ValueError:
                pass

        for d in deleted_dirs:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

        # Remove from ModsConfig.xml (best-effort — might not know packageId)
        for d in deleted_dirs:
            about = _read_about(d) if d.exists() else {"packageId": d.name.lower()}
            self._deactivate_package(about["packageId"])

        print(f"✓ Uninstalled: {mod_name}")

    # ── List ─────────────────────────────────────────────────────────────────

    def list_mods(self) -> list[dict]:
        active_ids = set(_get_active_package_ids())
        result = []

        if not self.mods_dir.exists():
            return result

        manifest = load_manifest()
        game_slug = self._game_slug()

        # Tracked mods first
        tracked_dirs: set[str] = set()
        for mod_name, entry in manifest.items():
            if entry.get("game") not in (None, game_slug):
                continue
            files = entry.get("files", [])
            if not files:
                continue
            # Determine mod folder from first file
            mod_dir = None
            for f_str in files:
                f = Path(f_str)
                try:
                    rel = f.relative_to(self.mods_dir)
                    mod_dir = self.mods_dir / rel.parts[0]
                    break
                except ValueError:
                    pass
            if mod_dir is None:
                continue
            tracked_dirs.add(mod_dir.name)
            about = _read_about(mod_dir) if mod_dir.exists() else {"packageId": mod_dir.name.lower(), "name": mod_name}
            active = about["packageId"] in active_ids
            result.append({
                "name": mod_name, "display": about["name"],
                "packageId": about["packageId"], "active": active, "plugins": [],
            })

        # Untracked mods in Mods/ dir
        for mod_dir in sorted(self.mods_dir.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name in tracked_dirs:
                continue
            about = _read_about(mod_dir)
            active = about["packageId"] in active_ids
            result.append({
                "name": mod_dir.name, "display": about["name"],
                "packageId": about["packageId"], "active": active, "plugins": [], "untracked": True,
            })

        return result

    # ── Load order ────────────────────────────────────────────────────────────

    def get_load_order(self) -> list[str]:
        """Return ordered list of active mod package IDs."""
        return _get_active_package_ids()

    def set_load_order(self, order: list[str]) -> None:
        """Write new activeMods order to ModsConfig.xml."""
        if not MODSCONFIG_PATH.exists():
            return
        tree, active_mods = _read_modsconfig()
        for li in list(active_mods):
            active_mods.remove(li)
        for pkg_id in order:
            li = ET.SubElement(active_mods, "li")
            li.text = pkg_id
        _write_modsconfig(tree)

    # ── Activation ────────────────────────────────────────────────────────────

    def enable_mod(self, mod_name: str) -> None:
        pkg_id = self._package_id_for(mod_name)
        if pkg_id:
            self._activate_package(pkg_id)
            print(f"✓ enabled: {mod_name}")

    def disable_mod(self, mod_name: str) -> None:
        pkg_id = self._package_id_for(mod_name)
        if pkg_id:
            self._deactivate_package(pkg_id)
            print(f"✓ disabled: {mod_name}")

    def _package_id_for(self, mod_name: str) -> str | None:
        """Resolve mod_name → packageId via manifest or Mods/ scan."""
        manifest = load_manifest()
        game_slug = self._game_slug()
        entry = manifest.get(mod_name)
        if entry and entry.get("game") in (None, game_slug):
            files = entry.get("files", [])
            for f_str in files:
                f = Path(f_str)
                try:
                    rel = f.relative_to(self.mods_dir)
                    mod_dir = self.mods_dir / rel.parts[0]
                    return _read_about(mod_dir)["packageId"]
                except (ValueError, IndexError):
                    pass
        # Fallback: scan Mods/ by name
        candidate = self.mods_dir / mod_name
        if candidate.exists():
            return _read_about(candidate)["packageId"]
        return None

    def _activate_package(self, package_id: str) -> None:
        if not MODSCONFIG_PATH.exists():
            return
        tree, active_mods = _read_modsconfig()
        existing = [li.text.strip().lower() for li in active_mods.findall("li") if li.text]
        if package_id.lower() not in existing:
            li = ET.SubElement(active_mods, "li")
            li.text = package_id
            _write_modsconfig(tree)

    def _deactivate_package(self, package_id: str) -> None:
        if not MODSCONFIG_PATH.exists():
            return
        tree, active_mods = _read_modsconfig()
        for li in list(active_mods.findall("li")):
            if li.text and li.text.strip().lower() == package_id.lower():
                active_mods.remove(li)
        _write_modsconfig(tree)
