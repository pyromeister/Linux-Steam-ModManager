import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

from lsmm.core import profiles as prof
from lsmm.core.config import get_nexus_api_key


def rebuild_profiles_popover(window, popover):
    from lsmm.gui.dialogs.collection import show_collection_mods_dialog

    box = window._profiles_popover_box
    while child := box.get_first_child():
        box.remove(child)

    if not window.engine:
        no_game = Gtk.Label(label="Select a game first")
        no_game.add_css_class("dim-label")
        box.append(no_game)
        return

    slug = window._game_slug
    all_profiles = prof.load_all(slug)

    # ── Save section ──
    save_label = Gtk.Label(label="Save current as:")
    save_label.set_xalign(0)
    save_label.add_css_class("caption")
    box.append(save_label)

    save_entry = Gtk.Entry()
    save_entry.set_placeholder_text("Profile name")
    box.append(save_entry)

    save_btn = Gtk.Button(label="Save Profile")
    save_btn.add_css_class("suggested-action")

    def do_save(_btn):
        name = save_entry.get_text().strip()
        if not name:
            return
        active = [m["name"] for m in window.engine.list_mods() if m["active"]]
        order = window.engine.get_load_order() if window.engine.has_load_order else []
        prof.save(slug, name, active, order)
        window._toast(f"Saved profile: {name}")
        popover.popdown()

    save_btn.connect("clicked", do_save)
    box.append(save_btn)

    # ── Load / Delete section ──
    if all_profiles:
        sep = Gtk.Separator()
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        box.append(sep)

        load_label = Gtk.Label(label="Saved profiles:")
        load_label.set_xalign(0)
        load_label.add_css_class("caption")
        box.append(load_label)

        profile_names = list(all_profiles.keys())
        dropdown = Gtk.DropDown.new_from_strings(profile_names)
        box.append(dropdown)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        load_btn = Gtk.Button(label="Load")
        load_btn.set_hexpand(True)

        del_btn = Gtk.Button(label="Delete")
        del_btn.add_css_class("destructive-action")
        del_btn.set_hexpand(True)

        def do_load(_btn):
            name = profile_names[dropdown.get_selected()]
            popover.popdown()
            apply_profile(window, slug, name)

        def do_delete(_btn):
            name = profile_names[dropdown.get_selected()]
            prof.delete(slug, name)
            window._toast(f"Deleted profile: {name}")
            popover.popdown()

        def do_update(_btn):
            name = profile_names[dropdown.get_selected()]
            active = [m["name"] for m in window.engine.list_mods() if m["active"]]
            order = window.engine.get_load_order() if window.engine.has_load_order else []
            existing = prof.get(slug, name) or {}
            prof.save(slug, name, active, order,
                      collection_mods=existing.get("collection_mods"),
                      collection_game_domain=existing.get("collection_game_domain"))
            window._toast(f"Saved: {name}")
            popover.popdown()

        update_btn = Gtk.Button(label="Save")
        update_btn.add_css_class("suggested-action")
        update_btn.set_hexpand(True)

        load_btn.connect("clicked", do_load)
        del_btn.connect("clicked", do_delete)
        update_btn.connect("clicked", do_update)
        btn_row.append(load_btn)
        btn_row.append(update_btn)
        btn_row.append(del_btn)
        box.append(btn_row)

        def do_check_mods(_btn):
            name = profile_names[dropdown.get_selected()]
            popover.popdown()
            show_collection_mods_dialog(window, name, slug)

        check_btn = Gtk.Button(label="Check Mods")
        check_btn.connect("clicked", do_check_mods)
        box.append(check_btn)

    # ── Import modpack section ──
    sep2 = Gtk.Separator()
    sep2.set_margin_top(4)
    sep2.set_margin_bottom(4)
    box.append(sep2)

    import_label = Gtk.Label(label="Import Modpack from Nexus:")
    import_label.set_xalign(0)
    import_label.add_css_class("caption")
    box.append(import_label)

    import_entry = Gtk.Entry()
    import_entry.set_placeholder_text("https://www.nexusmods.com/…/collections/…")
    box.append(import_entry)

    import_btn = Gtk.Button(label="Import Modpack")

    def do_import(_btn):
        url = import_entry.get_text().strip()
        if not url:
            return
        popover.popdown()
        on_import_collection(window, url)

    import_btn.connect("clicked", do_import)
    box.append(import_btn)


def on_import_collection(window, url: str):
    from lsmm.gui.dialogs.collection import show_collection_import_dialog

    if not window.engine:
        window._toast("Select a game first")
        return

    import re
    m = re.search(r"nexusmods\.com/(?:games/)?([^/]+)/collections/([a-z0-9]+)", url, re.I)
    if not m:
        window._toast("Invalid collection URL — expected nexusmods.com/…/collections/…")
        return

    collection_slug = m.group(2)
    slug = window._game_slug
    api_key = get_nexus_api_key()

    def run():
        collection_name = collection_slug
        collection_mods = None
        game_domain = None
        if api_key:
            from lsmm.core.nexus import fetch_collection_graphql
            info = fetch_collection_graphql(collection_slug, api_key)
            if info:
                collection_name = info.get("name") or collection_slug
                collection_mods = info.get("mods")
                game_domain = info.get("game_domain")

        prof.save(slug, collection_name, [], [],
                  collection_mods=collection_mods,
                  collection_game_domain=game_domain)
        mod_count = len(collection_mods) if collection_mods else 0
        GLib.idle_add(show_collection_import_dialog, window, collection_name, mod_count)

    threading.Thread(target=run, daemon=True).start()


def apply_profile(window, slug: str, name: str):
    data = prof.get(slug, name)
    if not data:
        window._toast(f"Profile not found: {name}")
        return

    active_set = set(data.get("active_mods", []))
    for mod in window.engine.list_mods():
        if mod["kind"] == "mod":
            if mod["name"] in active_set:
                window.engine.enable_mod(mod["name"])
            else:
                window.engine.disable_mod(mod["name"])

    order = data.get("load_order", [])
    if order and window.engine.has_load_order:
        window.engine.set_load_order(order)

    window._refresh_mods()
    window._refresh_load_order()
    window._toast(f"Loaded profile: {name}")
