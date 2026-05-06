import logging
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from lsmm.core.config import ARCHIVES_DIR
from lsmm.core.installer import ConflictError
from lsmm.core.nexus import NxmExpiredError, nxm_error_message as _nxm_error_message

logger = logging.getLogger(__name__)


def do_nxm_import(window, url: str, api_key: str):
    from lsmm.core.nexus import parse_nxm, get_download_link, get_mod_files, download_file

    nxm = parse_nxm(url.strip())
    if not nxm:
        window._toast("Invalid NXM URL — expected nxm://...")
        return

    if nxm.get("expires") and int(nxm["expires"]) < int(time.time()):
        window._toast("This Nexus download link has expired — click the download button again on Nexus Mods")
        return

    def run():
        try:
            GLib.idle_add(window.status_label.set_text, "Getting download link from Nexus...")
            try:
                dl_url = get_download_link(nxm, api_key)
            except Exception as link_err:
                GLib.idle_add(window._progress_done)
                GLib.idle_add(window.status_label.set_text, "Ready")
                GLib.idle_add(window._toast, _nxm_error_message(link_err))
                return

            filename = dl_url.split("/")[-1].split("?")[0]
            slug = window._game_slug or "unknown"
            dest = ARCHIVES_DIR / slug / filename

            file_entry = None
            try:
                files = get_mod_files(nxm["game_domain"], nxm["mod_id"], api_key)
                file_entry = next((f for f in files if f.get("file_id") == nxm["file_id"]), None)
                expected_md5 = file_entry.get("md5") if file_entry else None
            except Exception:
                expected_md5 = None

            GLib.idle_add(window.status_label.set_text, f"Downloading {filename}...")
            GLib.idle_add(window._progress_set, 0.0)

            def on_dl_progress(downloaded: int, total: int) -> None:
                if total > 0:
                    GLib.idle_add(window._progress_set, downloaded / total)

            download_file(dl_url, dest, on_progress=on_dl_progress, expected_md5=expected_md5)

            GLib.idle_add(window.status_label.set_text, f"Installing {filename}...")
            GLib.idle_add(window._progress_start_pulse)
            nexus_meta = {
                "game_domain": nxm["game_domain"],
                "mod_id": nxm["mod_id"],
                "file_id": nxm["file_id"],
            }
            if file_entry:
                for key in ("version", "size_kb", "uploaded_timestamp"):
                    if file_entry.get(key) is not None:
                        nexus_meta[key] = file_entry[key]
            try:
                window.engine.install(dest, nexus_meta=nexus_meta)
            except ConflictError as ce:
                from lsmm.gui.handlers.install import ask_conflict
                confirmed = ask_conflict(window, ce.conflicts, filename)
                if confirmed:
                    window.engine.install(dest, force=True, nexus_meta=nexus_meta)
                else:
                    GLib.idle_add(window._progress_done)
                    GLib.idle_add(window.status_label.set_text, "Ready")
                    return

            GLib.idle_add(window._progress_done)
            GLib.idle_add(window.status_label.set_text, "Ready")
            GLib.idle_add(window._refresh_mods)
            GLib.idle_add(window._refresh_load_order)
            GLib.idle_add(window._toast, f"Installed: {filename}")

        except NxmExpiredError:
            GLib.idle_add(window._progress_done)
            GLib.idle_add(window.status_label.set_text, "Ready")
            GLib.idle_add(
                window._toast,
                "This Nexus download link has expired. "
                "Click 'Mod Manager Download' on Nexus again.",
            )
        except Exception as e:
            logger.error("NXM import error: %s", e)
            GLib.idle_add(window._progress_done)
            GLib.idle_add(window.status_label.set_text, "Ready")
            GLib.idle_add(window._toast, _nxm_error_message(e))

    threading.Thread(target=run, daemon=True).start()
