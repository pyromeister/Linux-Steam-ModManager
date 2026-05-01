"""Steam installation path selection dialog."""

from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.config import save_steam_root, get_steam_candidates


def _steam_path_label(path) -> str:
    s = str(path)
    if ".var/app/" in s:
        return "Flatpak"
    if "/snap/" in s:
        return "Snap"
    return "Native"


def apply_steam_path(win, chosen: Path):
    if (chosen / "steamapps").exists():
        save_steam_root(chosen)
        win._refresh_games()
    else:
        win._toast("That folder is not a valid Steam installation (no steamapps/ found)")
        show_steam_path_dialog(win, get_steam_candidates())


def _on_steam_folder_selected(win, dialog, result):
    try:
        folder = dialog.select_folder_finish(result)
    except Exception:
        return
    if folder is not None:
        apply_steam_path(win, Path(folder.get_path()))


def _on_steam_path_response(win, candidates, dialog, response_id: str):
    if response_id == "browse":
        folder_dialog = Gtk.FileDialog()
        folder_dialog.set_title("Select Steam data folder")
        folder_dialog.select_folder(win, None, lambda d, r: _on_steam_folder_selected(win, d, r))
        return
    apply_steam_path(win, candidates[int(response_id)])


def show_steam_path_dialog(win, candidates: list):
    if not candidates:
        body = (
            "Steam was not found automatically.\n"
            "Please select your Steam data folder manually.\n\n"
            "Typical location: <tt>~/.local/share/Steam</tt>"
        )
    else:
        lines = "\n".join(
            f"{i+1}. <tt>{p}</tt>  ({_steam_path_label(p)})"
            for i, p in enumerate(candidates)
        )
        body = (
            f"Multiple Steam installations were detected:\n\n{lines}\n\n"
            "Select one below, or browse to a custom location."
        )

    dialog = Adw.MessageDialog(transient_for=win, heading="Steam Installation")
    dialog.set_body(body)
    dialog.set_body_use_markup(True)

    for i in range(len(candidates)):
        dialog.add_response(str(i), str(i + 1))

    dialog.add_response("browse", "Browse…")
    dialog.connect("response", lambda d, r: _on_steam_path_response(win, candidates, d, r))
    dialog.present()
