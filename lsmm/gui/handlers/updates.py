import threading

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib


def do_check_updates(window, api_key: str):
    from lsmm.core.nexus import check_update
    from lsmm.core.installer import load_manifest
    from lsmm.gui.dialogs.update_results import show_update_results

    def run():
        GLib.idle_add(window.status_label.set_text, "Checking for updates...")
        manifest = load_manifest()
        updates: list = []
        errors: list = []
        game_slug = window._game_slug

        for mod_name, entry in manifest.items():
            if entry.get("game") not in (None, game_slug):
                continue
            nx = entry.get("nexus")
            if not nx:
                continue
            try:
                latest = check_update(nx["game_domain"], nx["mod_id"], nx["file_id"], api_key)
                if latest:
                    updates.append((
                        mod_name,
                        str(nx.get("file_id", "?")),
                        latest.get("version") or str(latest.get("file_id", "?")),
                    ))
            except Exception as e:
                errors.append(f"{mod_name}: {e}")

        GLib.idle_add(window.status_label.set_text, "Ready")
        GLib.idle_add(show_update_results, window, updates, errors)

    threading.Thread(target=run, daemon=True).start()
