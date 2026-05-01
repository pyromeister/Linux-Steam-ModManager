import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from lsmm.core.installer import ConflictError


def ask_conflict(window, conflicts: list, mod_name: str) -> bool:
    """Block the calling thread until the user responds to a conflict dialog."""
    from lsmm.gui.dialogs.conflict import show_conflict_dialog
    event = threading.Event()
    result = [False]
    GLib.idle_add(show_conflict_dialog, window, conflicts, mod_name, event, result)
    event.wait()
    return result[0]


def install_batch(window, paths: list):
    if window._installing:
        window._toast("Installation already in progress")
        return

    window._installing = True

    def run():
        GLib.idle_add(window._progress_start_pulse)
        for i, path in enumerate(paths):
            GLib.idle_add(
                window.status_label.set_text,
                f"Installing {path.name} ({i + 1}/{len(paths)})..."
            )
            try:
                window.engine.install(path)
            except ConflictError as ce:
                confirmed = ask_conflict(window, ce.conflicts, path.name)
                if confirmed:
                    try:
                        window.engine.install(path, force=True)
                    except Exception as e:
                        GLib.idle_add(window._toast, f"Failed: {path.name} — {e}")
            except Exception as e:
                GLib.idle_add(window._toast, f"Failed: {path.name} — {e}")

        window._installing = False
        GLib.idle_add(window._progress_done)
        GLib.idle_add(window.status_label.set_text, "Ready")
        GLib.idle_add(window._refresh_mods)
        GLib.idle_add(window._refresh_load_order)

    threading.Thread(target=run, daemon=True).start()


def do_uninstall(window, mod_name: str):
    def run():
        window.engine.uninstall(mod_name)
        GLib.idle_add(window._refresh_mods)
        GLib.idle_add(window._refresh_load_order)
        GLib.idle_add(window._update_setup_btn)
        GLib.idle_add(window._toast, f"Uninstalled: {mod_name}")
    threading.Thread(target=run, daemon=True).start()
