"""BepInEx framework and Script Extender setup handlers."""

import threading

import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib


def handle_setup_btn(win):
    if not win.engine:
        return
    if getattr(win.engine, "has_framework_setup", False):
        handle_setup_bepinex(win)
    else:
        handle_setup_se(win)


def handle_setup_bepinex(win):
    fw = getattr(win.engine, "framework_name", "BepInEx")
    if win.engine.is_framework_installed():
        show_bepinex_launch_dialog(win)
        return

    dialog = Adw.MessageDialog(
        transient_for=win,
        heading=f"Install {fw}",
        body=(
            f"The latest {fw} release will be downloaded from GitHub "
            f"and extracted to:\n<tt>{GLib.markup_escape_text(str(win.engine.game_root))}</tt>\n\n"
            f"{fw} is required for mods to work in this game."
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("install", "Download & Install")
    dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("install")
    dialog.connect("response", lambda d, r: do_setup_bepinex(win) if r == "install" else None)
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
            f"{clipboard_note}"
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "OK")
    dialog.present()


def do_setup_bepinex(win):
    def run():
        GLib.idle_add(win.status_label.set_text, "Fetching BepInEx release info...")
        GLib.idle_add(win._progress_set, 0.0)
        try:
            def on_progress(downloaded, total):
                if total > 0:
                    GLib.idle_add(win._progress_set, downloaded / total)
                GLib.idle_add(
                    win.status_label.set_text,
                    f"Downloading BepInEx... {downloaded // 1024} KB"
                    + (f" / {total // 1024} KB" if total > 0 else ""),
                )

            version = win.engine.setup_framework(on_progress=on_progress)

            GLib.idle_add(win._progress_start_pulse)
            GLib.idle_add(win.status_label.set_text, "Extracting BepInEx...")
            GLib.idle_add(win._progress_done)
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._update_setup_btn)
            GLib.idle_add(win._refresh_mods)
            GLib.idle_add(show_bepinex_launch_dialog, win)
            GLib.idle_add(win._toast, f"BepInEx {version} installed successfully")
        except Exception as e:
            GLib.idle_add(win._progress_done)
            GLib.idle_add(win.status_label.set_text, "Ready")
            GLib.idle_add(win._toast, f"BepInEx install failed: {e}")

    threading.Thread(target=run, daemon=True).start()


def handle_setup_se(win):
    if not win.engine or not win.engine.has_script_extender:
        win._toast("No script extender for this game")
        return
    try:
        script_path = win.engine.setup_script_extender()
    except Exception as e:
        win._toast(f"Setup failed: {e}")
        return

    launch_option = f'"{script_path}" %command%'

    copied = False
    try:
        win.get_display().get_clipboard().set(launch_option)
        copied = True
    except Exception:
        pass

    clipboard_note = "\nThe text has been copied to your clipboard." if copied else ""
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading="Script Extender Setup Complete",
        body=(
            "A launch script was created. Add the following to your game's "
            "<b>Steam Launch Options</b> (right-click game → Properties → General):\n\n"
            f"<tt>{GLib.markup_escape_text(launch_option)}</tt>"
            f"{clipboard_note}"
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "OK")
    dialog.present()
