"""Game list panel builder and management handlers."""

import shutil
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gtk, Gio, Pango

from lsmm.core.config import GAMES_DIR
from lsmm.core.utils import available_games


def _list_store_from_filter(f: Gtk.FileFilter) -> Gio.ListStore:
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    return store


def build_games_panel(win) -> Gtk.Box:
    """Build the games column panel, setting win.games_list and win.remove_game_btn."""
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    panel.set_size_request(200, -1)

    header_label = Gtk.Label(label="Games")
    header_label.add_css_class("heading")
    header_label.set_margin_top(12)
    header_label.set_margin_bottom(8)
    panel.append(header_label)

    win._games_search = Gtk.SearchEntry()
    win._games_search.set_placeholder_text("Search games…")
    win._games_search.set_margin_start(12)
    win._games_search.set_margin_end(12)
    win._games_search.set_margin_bottom(8)

    def _on_games_search_changed(entry):
        win._games_search_query = entry.get_text().strip().lower()
        win.games_list.invalidate_filter()

    win._games_search.connect("search-changed", _on_games_search_changed)
    panel.append(win._games_search)

    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    panel.append(scroll)

    win._games_search_query = ""

    def _games_filter(row):
        q = win._games_search_query
        if not q:
            return True
        label = row.get_child()
        name = label.get_label().lower() if label else ""
        return q in name or q in getattr(row, "_slug", "").replace("_", " ")

    win.games_list = Gtk.ListBox()
    win.games_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
    win.games_list.add_css_class("boxed-list")
    win.games_list.set_margin_start(12)
    win.games_list.set_margin_end(12)
    win.games_list.set_filter_func(_games_filter)
    win.games_list.connect("row-activated", lambda lb, row: on_game_row_activated(win, row))
    scroll.set_child(win.games_list)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    btn_box.set_margin_start(12)
    btn_box.set_margin_end(12)
    btn_box.set_margin_top(8)
    btn_box.set_margin_bottom(10)

    add_btn = Gtk.Button(label="+ Add")
    add_btn.set_hexpand(True)
    add_btn.connect("clicked", lambda btn: add_game(win, btn))
    btn_box.append(add_btn)

    win.remove_game_btn = Gtk.Button(label="- Remove")
    win.remove_game_btn.set_hexpand(True)
    win.remove_game_btn.add_css_class("destructive-action")
    win.remove_game_btn.connect("clicked", lambda btn: confirm_remove_game(win, btn))
    win.remove_game_btn.set_sensitive(False)
    btn_box.append(win.remove_game_btn)

    panel.append(btn_box)
    return panel


def refresh_games(win):
    while child := win.games_list.get_first_child():
        win.games_list.remove(child)
    win.games = available_games()
    for slug, name in win.games:
        row = Gtk.ListBoxRow()
        row._slug = slug
        lbl = Gtk.Label(label=name)
        lbl.set_xalign(0)
        lbl.set_margin_start(8)
        lbl.set_margin_end(8)
        lbl.set_margin_top(6)
        lbl.set_margin_bottom(6)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        row.set_child(lbl)
        win.games_list.append(row)
    if win._game_slug:
        for row in win._iter_game_rows():
            if row._slug == win._game_slug:
                win.games_list.select_row(row)
                win.remove_game_btn.set_sensitive(True)
                break


def on_game_row_activated(win, row):
    win.remove_game_btn.set_sensitive(True)
    win._select_game(row._slug)


def add_game(win, _btn):
    dialog = Gtk.FileDialog()
    dialog.set_title("Select game profile (.json)")
    filters = Gtk.FileFilter()
    filters.set_name("JSON profiles (*.json)")
    filters.add_pattern("*.json")
    dialog.set_filters(_list_store_from_filter(filters))
    dialog.set_initial_folder(Gio.File.new_for_path(str(GAMES_DIR)))
    dialog.open(win, None, lambda d, r: _on_game_profile_selected(win, d, r))


def _on_game_profile_selected(win, dialog, result):
    try:
        f = dialog.open_finish(result)
    except Exception:
        return
    if f is None:
        return
    src = Path(f.get_path())
    dst = GAMES_DIR / src.name
    if dst.exists():
        win._toast(f"Profile already exists: {src.name}")
        return
    try:
        shutil.copy2(src, dst)
        win._refresh_games()
        win._toast(f"Added game profile: {src.stem}")
    except Exception as e:
        win._toast(f"Failed to add profile: {e}")


def confirm_remove_game(win, _btn):
    row = win.games_list.get_selected_row()
    if row is None:
        return
    slug = row._slug
    _, name = next(((s, n) for s, n in win.games if s == slug), (slug, slug))
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading=f'Remove "{name}"?',
        body="This deletes the game profile file from games/. Installed mods are not affected.",
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("remove", "Remove Profile")
    dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.connect("response", lambda d, r: do_remove_game(win, slug) if r == "remove" else None)
    dialog.present()


def do_remove_game(win, slug: str):
    path = GAMES_DIR / f"{slug}.json"
    try:
        path.unlink()
    except Exception as e:
        win._toast(f"Failed to remove: {e}")
        return
    if win._game_slug == slug:
        win.engine = None
        win._game_slug = None
        win.set_title("Linux Steam ModManager")
        win._refresh_mods()
        win._refresh_load_order()
        win.remove_game_btn.set_sensitive(False)
    win._refresh_games()
    win._toast(f"Removed profile: {slug}")
