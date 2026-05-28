"""BepInEx framework and Script Extender setup handlers."""

import logging
import threading

import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

logger = logging.getLogger(__name__)


def handle_setup_btn(win):
    if not win.engine:
        return
    if getattr(win.engine, "has_framework_setup", False):
        handle_setup_bepinex(win)
    else:
        handle_setup_se(win)


def handle_setup_bepinex(win):
    fw = getattr(win.engine, "framework_name", "BepInEx")
    slug = win._game_slug or ""
    update_available = slug in win._fw_update_available

    if win.engine.is_framework_installed() and not update_available:
        show_bepinex_launch_dialog(win)
        return

    if update_available:
        heading = f"Update {fw}"
        body = (
            f"A newer version of {fw} is available. "
            f"The latest release will be downloaded from GitHub "
            f"and installed to:\n<tt>{GLib.markup_escape_text(str(win.engine.game_root))}</tt>"
        )
        action_label = "Download & Update"
    else:
        heading = f"Install {fw}"
        body = (
            f"The latest {fw} release will be downloaded from GitHub "
            f"and extracted to:\n<tt>{GLib.markup_escape_text(str(win.engine.game_root))}</tt>\n\n"
            f"{fw} is required for mods to work in this game."
        )
        action_label = "Download & Install"

    dialog = Adw.MessageDialog(transient_for=win, heading=heading, body=body)
    dialog.set_body_use_markup(True)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("confirm", action_label)
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("confirm")
    dialog.connect("response", lambda d, r: do_setup_bepinex(win) if r == "confirm" else None)
    dialog.present()


def show_bepinex_launch_dialog(win):
    try:
        launch_option = win.engine.setup_launch()
    except RuntimeError as e:
        win._toast(str(e))
        return

    copied = False
    try:
        win.get_display().get_clipboard().set(launch_option)
        copied = True
    except Exception:
        pass

    fw = getattr(win.engine, "framework_name", "BepInEx")
    clipboard_note = "\nCopied to clipboard." if copied else ""
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading=f"{fw} Launch Setup",
        body=(
            f"{fw} is installed. To activate mods, set this as your "
            "<b>Steam Launch Option</b> "
            "(right-click game → Properties → General):\n\n"
            f"<tt>{GLib.markup_escape_text(launch_option)}</tt>"
            f"{clipboard_note}\n\n"
            "Or use the <b>▶ Launch</b> button in this app to launch directly."
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "OK")
    dialog.present()


def do_setup_bepinex(win):
    fw = getattr(win.engine, "framework_name", "BepInEx")

    def run():
        GLib.idle_add(win.status_label.set_text, f"Fetching {fw} release info...")
        GLib.idle_add(win._progress_set, 0.0)
        try:
            def on_progress(downloaded, total):
                if total > 0:
                    GLib.idle_add(win._progress_set, downloaded / total)
                GLib.idle_add(
                    win.status_label.set_text,
                    f"Downloading {fw}... {downloaded // 1024} KB"
                    + (f" / {total // 1024} KB" if total > 0 else ""),
                )

            version = win.engine.setup_framework(on_progress=on_progress)

            GLib.idle_add(win._progress_start_pulse)
            GLib.idle_add(win.status_label.set_text, f"Extracting {fw}...")
            win._se_version_cache.pop(win._game_slug or "", None)
            win._se_check_in_flight.discard(win._game_slug or "")
            win._fw_update_available.discard(win._game_slug or "")
            GLib.idle_add(win._progress_done)
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._update_setup_btn)
            GLib.idle_add(win._refresh_all)
            GLib.idle_add(show_bepinex_launch_dialog, win)
            GLib.idle_add(win._toast, f"{fw} {version} installed successfully")
        except Exception as e:
            logger.error("%s install failed: %s", fw, e, exc_info=True)
            GLib.idle_add(win._progress_done)
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._toast, f"{fw} install failed: {e}")

    threading.Thread(target=run, daemon=True).start()


def handle_setup_se(win):
    if not win.engine or not win.engine.has_script_extender:
        win._toast("No script extender for this game")
        return

    paths = getattr(win.engine, "paths", None)
    se = win.engine.profile.get("script_extender", {})
    se_name = se.get("name", "Script Extender")
    se_installed = bool(paths and paths.se_loader and paths.se_loader.exists())

    if se_installed:
        _finish_se_setup(win)
        return

    # No auto-install available — open download page if configured
    if not se.get("github_repo"):
        download_page = se.get("download_page")
        if download_page:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
            Gtk.UriLauncher.new(download_page).launch(win, None, None, None)
            win._toast(f"Opening {se_name} download page…")
        else:
            game_root = str(getattr(paths, "game_root", "the game folder"))
            _show_manual_install_dialog(win, se_name, game_root)
        return

    # SE not installed — fetch release info and show confirm dialog
    def fetch_and_confirm():
        GLib.idle_add(win.status_label.set_text, f"Fetching {se_name} release info…")
        try:
            info = win.engine.get_se_latest_info()
        except Exception as e:
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._toast, f"Could not fetch {se_name} info: {e}")
            return
        GLib.idle_add(win.status_label.set_text, "Ready")
        if info is None:
            GLib.idle_add(
                win._toast,
                f"No GitHub release found for {se_name} — install manually and retry",
            )
            return
        version, url, _filename = info
        dest = str(getattr(paths, "game_root", "unknown"))
        GLib.idle_add(_show_se_confirm_dialog, win, se_name, version, url, dest)

    threading.Thread(target=fetch_and_confirm, daemon=True).start()


def _show_manual_install_dialog(win, se_name: str, game_root: str):
    body = (
        f"{se_name} cannot be downloaded automatically.\n\n"
        f"Download it manually from the official website, then extract the contents "
        f"into:\n<tt>{GLib.markup_escape_text(game_root)}</tt>\n\n"
        f"Once installed, click the button again to set up the Steam launch wrapper."
    )
    dialog = Adw.MessageDialog(transient_for=win, heading=f"Install {se_name} manually", body=body)
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "OK")
    dialog.set_default_response("ok")
    dialog.present()


def _show_se_confirm_dialog(win, se_name, version, url, dest):
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading=f"Download {se_name} {version}?",
        body=(
            f"<b>Source:</b> <tt>{GLib.markup_escape_text(url)}</tt>\n"
            f"<b>Destination:</b> <tt>{GLib.markup_escape_text(dest)}</tt>\n\n"
            f"{se_name} is required for script extender mods to work."
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("download", "Download & Install")
    dialog.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("download")

    def on_response(_d, response):
        if response == "download":
            _do_download_se(win, se_name)

    dialog.connect("response", on_response)
    dialog.present()


def _do_download_se(win, se_name: str):
    def run():
        GLib.idle_add(win._progress_set, 0.0)
        GLib.idle_add(win.status_label.set_text, f"Downloading {se_name}…")

        def on_progress(downloaded, total):
            if total > 0:
                GLib.idle_add(win._progress_set, downloaded / total)
            GLib.idle_add(
                win.status_label.set_text,
                f"Downloading {se_name}… {downloaded // 1024} KB"
                + (f" / {total // 1024} KB" if total > 0 else ""),
            )

        try:
            win.engine.download_script_extender(on_progress=on_progress)
            win._se_version_cache.pop(win._game_slug or "", None)
            win._se_check_in_flight.discard(win._game_slug or "")
            GLib.idle_add(win._progress_done)
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._update_setup_btn)
            GLib.idle_add(win._refresh_all)
            GLib.idle_add(_finish_se_setup, win)
        except Exception as e:
            logger.error("%s download failed: %s", se_name, e, exc_info=True)
            GLib.idle_add(win._progress_done)
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._toast, f"{se_name} download failed: {e}")

    threading.Thread(target=run, daemon=True).start()


def _finish_se_setup(win):
    try:
        script_path = win.engine.setup_script_extender()
    except Exception as e:
        logger.error("SE launch script setup failed: %s", e, exc_info=True)
        win._toast(f"Setup failed: {e}")
        return

    launch_option = f'"{script_path}" %command%'

    copied = False
    try:
        win.get_display().get_clipboard().set(launch_option)
        copied = True
    except Exception:
        pass

    clipboard_note = "\nCopied to clipboard." if copied else ""
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading="Script Extender Setup Complete",
        body=(
            "Add the following to your game's "
            "<b>Steam Launch Options</b> (right-click game → Properties → General):\n\n"
            f"<tt>{GLib.markup_escape_text(launch_option)}</tt>"
            f"{clipboard_note}\n\n"
            "This is a one-time step — once set, the ▶ Launch button handles everything."
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "OK")
    dialog.present()
