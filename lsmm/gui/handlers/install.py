import logging
import threading
from pathlib import Path

from lsmm.core.fomod import detect_fomod
from lsmm.core.installer import ConflictError, load_manifest, save_manifest
from lsmm.core.config import get_nexus_api_key
from lsmm.core.nexus import md5_file, search_by_md5

logger = logging.getLogger(__name__)


def _glib():
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib as _GLib
    return _GLib


def ask_conflict(window, conflicts: list, mod_name: str) -> bool:
    """Block the calling thread until the user responds to a conflict dialog."""
    from lsmm.gui.dialogs.conflict import show_conflict_dialog
    event = threading.Event()
    result = [False]
    _glib().idle_add(show_conflict_dialog, window, conflicts, mod_name, event, result)
    event.wait()
    return result[0]


def ask_fomod(window, config) -> list | None:
    """Block calling thread until user completes FOMOD dialog. Returns file list or None."""
    from lsmm.gui.dialogs.fomod import show_fomod_dialog
    event = threading.Event()
    result = [None]

    def show():
        def callback(files):
            result[0] = files
            event.set()
        show_fomod_dialog(window, config, callback)

    _glib().idle_add(show)
    event.wait()
    return result[0]


def _install_one(window, path, engine) -> bool:
    """Install a single archive. Returns True on success, False on failure."""
    config = detect_fomod(path)
    fomod_files = None
    if config is not None:
        fomod_files = ask_fomod(window, config)
        if fomod_files is None:
            return False

    try:
        engine.install(path, fomod_files=fomod_files)
        return True
    except ConflictError as ce:
        confirmed = ask_conflict(window, ce.conflicts, path.name)
        if confirmed:
            try:
                engine.install(path, force=True, fomod_files=fomod_files)
                return True
            except Exception as e:
                _glib().idle_add(window._toast, f"Failed: {path.name} — {e}")
                return False
        return False
    except Exception as e:
        _glib().idle_add(window._toast, f"Failed: {path.name} — {e}")
        return False


def _enrich_from_md5(window, path: Path, mod_name: str) -> None:
    """Background: compute MD5, query Nexus, patch manifest nexus sub-dict if matched."""
    api_key = get_nexus_api_key()
    if not api_key:
        return
    engine = window.engine
    if engine is None:
        return
    game_domain = (getattr(engine, "profile", None) or {}).get("nexus_domain")
    if not game_domain:
        return

    try:
        md5 = md5_file(path)
        result = search_by_md5(game_domain, md5, api_key)
    except Exception as e:
        logger.debug("MD5 Nexus lookup failed for %s: %s", path.name, e)
        return

    if not result:
        return

    manifest = load_manifest()
    entry = manifest.get(mod_name)
    if entry is None:
        return
    # Only enrich when the entry has no existing Nexus metadata
    if entry.get("nexus"):
        return

    entry["nexus"] = {
        "mod_id": result["mod_id"],
        "file_id": result["file_id"],
        "version": result.get("version"),
        "url": result.get("url"),
    }
    save_manifest(manifest)
    _glib().idle_add(window._refresh_mods)


def install_batch(window, paths: list):
    if window._installing:
        window._toast("Installation already in progress")
        return

    window._installing = True

    def run():
        _glib().idle_add(window._progress_start_pulse)
        succeeded = 0
        for i, path in enumerate(paths):
            _glib().idle_add(
                window.status_label.set_text,
                f"Installing {path.name} ({i + 1}/{len(paths)})..."
            )
            if _install_one(window, path, window.engine):
                succeeded += 1
                mod_name = path.stem
                threading.Thread(
                    target=_enrich_from_md5,
                    args=(window, path, mod_name),
                    daemon=True,
                ).start()

        window._installing = False
        _glib().idle_add(window._progress_done)
        _glib().idle_add(window.status_label.set_text, "Ready")
        _glib().idle_add(window._refresh_mods)
        _glib().idle_add(window._refresh_load_order)
        _glib().idle_add(window._refresh_mod_engine_tab)
        _glib().idle_add(window._refresh_profiles_tab)
        if len(paths) > 1:
            failed = len(paths) - succeeded
            msg = f"Installed {succeeded}/{len(paths)}"
            if failed:
                msg += f" — {failed} failed"
            _glib().idle_add(window._toast, msg)

    threading.Thread(target=run, daemon=True).start()


def do_uninstall(window, mod_name: str):
    def run():
        window.engine.uninstall(mod_name)
        _glib().idle_add(window._refresh_mods)
        _glib().idle_add(window._refresh_load_order)
        _glib().idle_add(window._refresh_mod_engine_tab)
        _glib().idle_add(window._refresh_profiles_tab)
        _glib().idle_add(window._update_setup_btn)
        _glib().idle_add(window._toast, f"Uninstalled: {mod_name}")
    threading.Thread(target=run, daemon=True).start()
