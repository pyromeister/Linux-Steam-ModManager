"""Profiles tab builder and management handlers."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core import profiles as _prof


class _TabRef:
    """Adapter so collection handlers can popdown() to trigger a tab refresh."""

    def __init__(self, refresh_fn):
        self._refresh = refresh_fn

    def popdown(self):
        self._refresh()


def build_profiles_tab(win) -> Gtk.Widget:
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    header.set_margin_start(12)
    header.set_margin_end(12)
    header.set_margin_top(12)
    header.set_margin_bottom(8)
    title = Gtk.Label(label="Profiles")
    title.add_css_class("heading")
    title.set_hexpand(True)
    title.set_xalign(0)
    header.append(title)
    win._profiles_active_label = Gtk.Label()
    win._profiles_active_label.add_css_class("dim-label")
    win._profiles_active_label.add_css_class("caption")
    win._profiles_active_label.set_valign(Gtk.Align.CENTER)
    header.append(win._profiles_active_label)
    panel.append(header)

    win._profiles_no_game = Gtk.Label(label="Select a game first")
    win._profiles_no_game.add_css_class("dim-label")
    win._profiles_no_game.set_vexpand(True)
    panel.append(win._profiles_no_game)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    scroll.set_visible(False)
    win._profiles_list = Gtk.ListBox()
    win._profiles_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
    win._profiles_list.connect("row-activated", lambda _l, row: on_load_profile(win, row.get_title()))
    win._profiles_list.add_css_class("boxed-list")
    win._profiles_list.set_margin_start(12)
    win._profiles_list.set_margin_end(12)
    win._profiles_list.set_margin_bottom(4)
    scroll.set_child(win._profiles_list)
    panel.append(scroll)
    win._profiles_scroll = scroll

    btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_bar.set_margin_start(12)
    btn_bar.set_margin_end(12)
    btn_bar.set_margin_top(8)
    btn_bar.set_margin_bottom(12)
    new_btn = Gtk.Button(label="+ New Profile")
    new_btn.set_hexpand(True)
    new_btn.connect("clicked", lambda btn: on_new_profile(win, btn))
    btn_bar.append(new_btn)
    import_btn = Gtk.Button(label="Import Modpack…")
    import_btn.set_hexpand(True)
    import_btn.connect("clicked", lambda btn: on_import_modpack(win, btn))
    btn_bar.append(import_btn)
    panel.append(btn_bar)

    # Kept for backward compat with collection.py handlers that reference it
    win._profiles_popover_box = Gtk.Box()
    win._profiles_popover_box.set_visible(False)
    panel.append(win._profiles_popover_box)

    return panel


def refresh_profiles_tab(win):
    if not win.engine or not win._game_slug:
        win._profiles_no_game.set_visible(True)
        win._profiles_scroll.set_visible(False)
        win._profiles_active_label.set_text("")
        return

    win._profiles_no_game.set_visible(False)
    win._profiles_scroll.set_visible(True)

    while child := win._profiles_list.get_first_child():
        win._profiles_list.remove(child)

    slug = win._game_slug
    all_profiles = _prof.load_all(slug)
    active_name = _prof.get_active(slug)
    win._profiles_active_label.set_text(f"Active: {active_name}" if active_name else "")

    mods_overview = None
    if win.engine:
        try:
            mods = win.engine.list_mods()
            mods_overview = (sum(1 for m in mods if m["active"]), len(mods))
        except Exception:
            pass

    for name in _prof.SYSTEM_PROFILES:
        win._profiles_list.append(_make_system_profile_row(win, name, active_name, mods_overview))

    for name, data in all_profiles.items():
        win._profiles_list.append(_make_profile_row(win, name, data, active_name, slug, mods_overview))


def _make_system_profile_row(win, name, active_name, mods_overview=None):
    row = Adw.ActionRow()
    row.set_title(name)
    if name == "Vanilla":
        row.set_subtitle("No mods active")
    elif name == "All Mods":
        total = mods_overview[1] if mods_overview else 0
        row.set_subtitle(f"All {total} installed mod{'s' if total != 1 else ''}" if total else "All installed mods")

    icon = Gtk.Image.new_from_icon_name("emblem-system-symbolic")
    icon.add_css_class("dim-label")
    row.add_prefix(icon)

    if name == active_name:
        check = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
        check.add_css_class("success")
        row.add_prefix(check)

    load_btn = Gtk.Button(label="Load")
    load_btn.set_valign(Gtk.Align.CENTER)
    load_btn.add_css_class("flat" if name == active_name else "suggested-action")
    load_btn.connect("clicked", lambda _b, n=name: on_load_profile(win, n))
    row.add_suffix(load_btn)
    return row


def _make_profile_row(win, name, data, active_name, slug, mods_overview=None):
    row = Adw.ActionRow()
    row.set_title(name)
    if mods_overview:
        n_active, total = mods_overview
        if n_active == total:
            row.set_subtitle(f"{total} mod{'s' if total != 1 else ''}")
        else:
            row.set_subtitle(f"{n_active} / {total} active")
    else:
        mod_count = len(data.get("active_mods", []))
        row.set_subtitle(f"{mod_count} mod{'s' if mod_count != 1 else ''}")

    if name == active_name:
        check = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
        check.add_css_class("success")
        row.add_prefix(check)

    load_btn = Gtk.Button(label="Load")
    load_btn.set_valign(Gtk.Align.CENTER)
    load_btn.add_css_class("flat" if name == active_name else "suggested-action")
    load_btn.connect("clicked", lambda _b, n=name: on_load_profile(win, n))
    row.add_suffix(load_btn)

    rename_btn = Gtk.Button(label="Rename")
    rename_btn.set_valign(Gtk.Align.CENTER)
    rename_btn.add_css_class("flat")
    rename_btn.connect("clicked", lambda _b, n=name: on_rename_profile(win, n))
    row.add_suffix(rename_btn)

    del_btn = Gtk.Button()
    del_btn.set_icon_name("user-trash-symbolic")
    del_btn.set_valign(Gtk.Align.CENTER)
    del_btn.add_css_class("flat")
    del_btn.connect("clicked", lambda _b, n=name: on_delete_profile(win, n))
    row.add_suffix(del_btn)

    return row


def on_new_profile(win, _btn):
    if not win.engine:
        win._toast("Select a game first")
        return
    dialog = Adw.MessageDialog(transient_for=win, heading="New Profile")
    entry = Gtk.Entry()
    entry.set_placeholder_text("Profile name")
    entry.set_activates_default(True)
    entry.set_margin_start(16)
    entry.set_margin_end(16)
    entry.set_margin_bottom(8)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("cancel")

    def on_response(_d, response):
        if response != "save":
            return
        pname = entry.get_text().strip()
        if not pname:
            win._toast("Profile name cannot be empty")
            return
        active = [m["name"] for m in win.engine.list_mods() if m["active"]]
        order = win.engine.get_load_order() if win.engine.has_load_order else []
        _prof.save(win._game_slug, pname, active, order)
        win._toast(f"Saved profile: {pname}")
        refresh_profiles_tab(win)

    dialog.connect("response", on_response)
    dialog.present()


_TOGGLEABLE_KINDS = {"mod", "se_plugin", "unmanaged"}


def _apply_system_profile(win, name: str):
    if not win.engine:
        return
    mods = win.engine.list_mods()
    if name == "Vanilla":
        for mod in mods:
            if mod.get("active") and mod.get("kind") in _TOGGLEABLE_KINDS:
                win.engine.disable_mod(mod["name"])
    elif name == "All Mods":
        for mod in mods:
            if not mod.get("active") and mod.get("kind") in _TOGGLEABLE_KINDS:
                win.engine.enable_mod(mod["name"])
    _prof.set_active(win._game_slug, name)
    win._refresh_all()
    win._toast(f"Loaded: {name}")


def on_load_profile(win, name: str):
    if name in _prof.SYSTEM_PROFILES:
        _apply_system_profile(win, name)
    else:
        from lsmm.gui.handlers.collection import apply_profile
        apply_profile(win, win._game_slug, name)
    refresh_profiles_tab(win)


def on_delete_profile(win, name: str):
    _prof.delete(win._game_slug, name)
    if _prof.get_active(win._game_slug) == name:
        _prof.set_active(win._game_slug, None)
    win._toast(f"Deleted profile: {name}")
    refresh_profiles_tab(win)


def on_rename_profile(win, old_name: str):
    from lsmm.gui.handlers.collection import _show_rename_dialog
    _show_rename_dialog(win, _TabRef(lambda: refresh_profiles_tab(win)), win._game_slug, old_name)


def on_import_modpack(win, _btn):
    from lsmm.gui.handlers.collection import on_import_collection
    if not win.engine:
        win._toast("Select a game first")
        return
    dialog = Adw.MessageDialog(transient_for=win, heading="Import Modpack from Nexus")
    entry = Gtk.Entry()
    entry.set_placeholder_text("https://www.nexusmods.com/…/collections/…")
    entry.set_activates_default(True)
    entry.set_margin_start(16)
    entry.set_margin_end(16)
    entry.set_margin_bottom(8)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("import", "Import")
    dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("import")
    dialog.set_close_response("cancel")

    def on_response(_d, response):
        if response != "import":
            return
        url = entry.get_text().strip()
        if url:
            on_import_collection(win, url)

    dialog.connect("response", on_response)
    dialog.present()
