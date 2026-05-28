import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

from lsmm.core.config import ARCHIVES_DIR, get_nexus_api_key
from lsmm.core.installer import ConflictError


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
            if not nx or not nx.get("game_domain"):
                continue
            try:
                latest = check_update(nx["game_domain"], nx["mod_id"], nx["file_id"], api_key)
                if latest:
                    updates.append((
                        mod_name,
                        str(nx.get("file_id", "?")),
                        latest.get("version") or str(latest.get("file_id", "?")),
                        nx["game_domain"],
                        nx["mod_id"],
                        latest.get("file_id"),
                        nx.get("version") or "",
                    ))
            except Exception as e:
                errors.append(f"{mod_name}: {e}")

        GLib.idle_add(window.status_label.set_text, "Ready")
        GLib.idle_add(show_update_results, window, updates, errors)

    threading.Thread(target=run, daemon=True).start()


def update_all_async(window, updates: list):
    from lsmm.core.nexus import get_download_link, download_file

    api_key = get_nexus_api_key()

    def run():
        browser_mods = []
        for mod_name, _old_fid, _new_ver, game_domain, mod_id, new_file_id, *_ in updates:
            nxm = {"game_domain": game_domain, "mod_id": mod_id, "file_id": new_file_id}
            try:
                GLib.idle_add(window.status_label.set_text, f"Updating {mod_name}…")
                dl_url = get_download_link(nxm, api_key)
                filename = dl_url.split("/")[-1].split("?")[0]
                slug = window._game_slug or "unknown"
                dest = ARCHIVES_DIR / slug / filename

                def on_progress(downloaded, total):
                    if total > 0:
                        GLib.idle_add(window._progress_set, downloaded / total)

                GLib.idle_add(window._progress_set, 0.0)
                download_file(dl_url, dest, on_progress=on_progress)
                GLib.idle_add(window._progress_start_pulse)
                try:
                    window.engine.install(dest)
                except ConflictError:
                    window.engine.install(dest, force=True)
            except Exception as e:
                if "403" in str(e):
                    browser_mods.append((game_domain, mod_id, mod_name))
                else:
                    GLib.idle_add(window._toast, f"Update failed for {mod_name}: {e}")

        if browser_mods:
            GLib.idle_add(
                window._toast,
                f"Free account: opening {len(browser_mods)} mod page(s) in browser…",
            )
            for game_domain, mod_id, _name in browser_mods:
                url = f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}"
                GLib.idle_add(
                    Gtk.UriLauncher.new(url).launch, window, None, None, None
                )

        GLib.idle_add(window._progress_done)
        GLib.idle_add(window.status_label.set_text, "Ready")
        if not browser_mods:
            GLib.idle_add(window._refresh_all)
            GLib.idle_add(window._toast, "All mods updated")

    threading.Thread(target=run, daemon=True).start()
