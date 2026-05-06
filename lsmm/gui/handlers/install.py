import threading

from lsmm.core.fomod import detect_fomod
from lsmm.core.installer import ConflictError


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


def _install_one(window, path, engine) -> None:
    """Install a single archive, handling FOMOD detection and dialog handoff."""
    config = detect_fomod(path)
    fomod_files = None
    if config is not None:
        fomod_files = ask_fomod(window, config)
        if fomod_files is None:
            return

    try:
        engine.install(path, fomod_files=fomod_files)
    except ConflictError as ce:
        confirmed = ask_conflict(window, ce.conflicts, path.name)
        if confirmed:
            try:
                engine.install(path, force=True, fomod_files=fomod_files)
            except Exception as e:
                _glib().idle_add(window._toast, f"Failed: {path.name} — {e}")
    except Exception as e:
        _glib().idle_add(window._toast, f"Failed: {path.name} — {e}")


def install_batch(window, paths: list):
    if window._installing:
        window._toast("Installation already in progress")
        return

    window._installing = True

    def run():
        _glib().idle_add(window._progress_start_pulse)
        for i, path in enumerate(paths):
            _glib().idle_add(
                window.status_label.set_text,
                f"Installing {path.name} ({i + 1}/{len(paths)})..."
            )
            _install_one(window, path, window.engine)

        window._installing = False
        _glib().idle_add(window._progress_done)
        _glib().idle_add(window.status_label.set_text, "Ready")
        _glib().idle_add(window._refresh_mods)
        _glib().idle_add(window._refresh_load_order)

    threading.Thread(target=run, daemon=True).start()


def do_uninstall(window, mod_name: str):
    def run():
        window.engine.uninstall(mod_name)
        _glib().idle_add(window._refresh_mods)
        _glib().idle_add(window._refresh_load_order)
        _glib().idle_add(window._update_setup_btn)
        _glib().idle_add(window._toast, f"Uninstalled: {mod_name}")
    threading.Thread(target=run, daemon=True).start()
