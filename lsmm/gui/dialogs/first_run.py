"""First-run setup wizard.

Shown the very first time LSMM is launched (no Steam root and no Nexus API
key in config). Walks the user through three steps:

    1. Welcome
    2. Steam path  (auto / pick from candidates / browse)
    3. Nexus API key  (optional — can be skipped)

Built from a chain of Adw.MessageDialogs to match the rest of the codebase
(see steam_path.py, api_key.py). Kept deliberately simple — no Carousel,
no custom widgets.
"""

from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.config import (
    get_steam_candidates,
    save_nexus_api_key,
    save_steam_root,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _steam_path_label(path: Path) -> str:
    s = str(path)
    if ".var/app/" in s:
        return "Flatpak"
    if "/snap/" in s:
        return "Snap"
    return "Native"


def _finish(win) -> None:
    """Wizard done — refresh games so any newly-saved Steam root takes effect."""
    win._refresh_games()
    win._toast("Setup complete")


# ── step 3: Nexus API key (optional) ─────────────────────────────────────────

def _show_api_key_step(win) -> None:
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading="Nexus API Key (optional)",
        body=(
            "A Nexus API key lets you import mods directly from "
            "<a href=\"https://www.nexusmods.com\">nexusmods.com</a> "
            "via <tt>nxm://</tt> links.\n\n"
            "Get a free key at "
            "<b>nexusmods.com → Account → API Keys</b>.\n\n"
            "You can skip this and add the key later from the menu."
        ),
    )
    dialog.set_body_use_markup(True)

    entry = Gtk.Entry()
    entry.set_placeholder_text("Paste your Nexus API key here")
    entry.set_activates_default(True)
    entry.set_margin_start(16)
    entry.set_margin_end(16)
    entry.set_margin_bottom(8)
    dialog.set_extra_child(entry)

    dialog.add_response("skip", "Skip")
    dialog.add_response("save", "Save & Finish")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("skip")

    def on_response(_d, response: str) -> None:
        if response == "save":
            key = entry.get_text().strip()
            if key:
                save_nexus_api_key(key)
        _finish(win)

    dialog.connect("response", on_response)
    dialog.present()


# ── step 2: Steam path ───────────────────────────────────────────────────────

def _apply_steam_path_then_continue(win, chosen: Path) -> None:
    if (chosen / "steamapps").exists():
        save_steam_root(chosen)
        _show_api_key_step(win)
    else:
        win._toast("That folder is not a valid Steam installation (no steamapps/ found)")
        _show_steam_step(win)


def _on_browse_finished(win, dialog, result) -> None:
    try:
        folder = dialog.select_folder_finish(result)
    except Exception:
        # User cancelled the file picker — re-present the step.
        _show_steam_step(win)
        return
    if folder is None:
        _show_steam_step(win)
        return
    _apply_steam_path_then_continue(win, Path(folder.get_path()))


def _show_steam_step(win) -> None:
    candidates = get_steam_candidates()

    # Exactly one candidate → auto-save and skip ahead with a confirmation note.
    if len(candidates) == 1:
        only = candidates[0]
        confirm = Adw.MessageDialog(
            transient_for=win,
            heading="Steam Detected",
            body=(
                f"Found your Steam installation at:\n\n"
                f"<tt>{only}</tt>  ({_steam_path_label(only)})"
            ),
        )
        confirm.set_body_use_markup(True)
        confirm.add_response("browse", "Choose Different…")
        confirm.add_response("ok", "Use This")
        confirm.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        confirm.set_default_response("ok")
        confirm.set_close_response("ok")

        def on_response(_d, response: str) -> None:
            if response == "browse":
                folder_dialog = Gtk.FileDialog()
                folder_dialog.set_title("Select Steam data folder")
                folder_dialog.select_folder(
                    win, None, lambda d, r: _on_browse_finished(win, d, r)
                )
                return
            _apply_steam_path_then_continue(win, only)

        confirm.connect("response", on_response)
        confirm.present()
        return

    # 0 or 2+ candidates → let user pick / browse.
    if not candidates:
        body = (
            "Steam was not found automatically.\n"
            "Please select your Steam data folder.\n\n"
            "Typical location: <tt>~/.local/share/Steam</tt>"
        )
    else:
        lines = "\n".join(
            f"{i+1}. <tt>{p}</tt>  ({_steam_path_label(p)})"
            for i, p in enumerate(candidates)
        )
        body = (
            f"Multiple Steam installations were detected:\n\n{lines}\n\n"
            "Pick one below, or browse to a custom location."
        )

    dialog = Adw.MessageDialog(transient_for=win, heading="Step 2 of 3 — Steam Installation")
    dialog.set_body(body)
    dialog.set_body_use_markup(True)

    for i in range(len(candidates)):
        dialog.add_response(str(i), str(i + 1))
    dialog.add_response("browse", "Browse…")

    def on_response(_d, response: str) -> None:
        if response == "browse":
            folder_dialog = Gtk.FileDialog()
            folder_dialog.set_title("Select Steam data folder")
            folder_dialog.select_folder(
                win, None, lambda d, r: _on_browse_finished(win, d, r)
            )
            return
        _apply_steam_path_then_continue(win, candidates[int(response)])

    dialog.connect("response", on_response)
    dialog.present()


# ── step 1: welcome ──────────────────────────────────────────────────────────

def show_first_run_wizard(win) -> None:
    """Entry point — runs Welcome → Steam → Nexus API key in sequence.

    Trigger condition (decided by the caller, not here):
        get_steam_root() is None and get_nexus_api_key() is None
    """
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading="Welcome to Linux Steam ModManager",
        body=(
            "This short setup will get LSMM ready to manage your mods.\n\n"
            "<b>Step 1 of 3 — Welcome</b>\n"
            "Step 2: locate your Steam installation.\n"
            "Step 3: (optional) add your Nexus Mods API key.\n\n"
            "It only takes a few seconds."
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("cancel", "Maybe Later")
    dialog.add_response("start", "Get Started")
    dialog.set_response_appearance("start", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("start")
    dialog.set_close_response("cancel")

    def on_response(_d, response: str) -> None:
        if response == "start":
            _show_steam_step(win)
        # else: user dismissed — they'll be prompted on next launch.

    dialog.connect("response", on_response)
    dialog.present()
