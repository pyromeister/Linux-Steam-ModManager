import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, GLib, Gtk, Pango

from lsmm.core import profiles as prof


def show_collection_import_dialog(parent, name: str, mod_count: int = 0):
    count_text = f" ({mod_count} mods)" if mod_count else ""
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading="Modpack Profile Created",
        body=(
            f"Profile <b>{GLib.markup_escape_text(name)}</b>"
            f"{GLib.markup_escape_text(count_text)} has been saved.\n\n"
            "Nexus Mods requires downloading each mod individually. "
            "Install the mods via <b>NXM links</b> on the collection page, "
            "then use <b>Profiles/Modpacks → Check Mods</b> to see what's still missing."
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "OK")
    dialog.set_default_response("ok")
    dialog.present()


def show_collection_mods_dialog(window, profile_name: str, game_slug: str):
    profile_data = prof.get(game_slug, profile_name) or {}
    collection_mods = profile_data.get("collection_mods", [])
    game_domain = profile_data.get("collection_game_domain", "")

    if not collection_mods:
        msg = Adw.MessageDialog(
            transient_for=window,
            heading="No mod list",
            body="This profile has no collection mod list. Re-import the collection URL to fetch it.",
        )
        msg.add_response("ok", "OK")
        msg.present()
        return

    installed_ids = window._get_installed_nexus_mod_ids(game_slug)
    installed_mods = [m for m in collection_mods if m["mod_id"] in installed_ids]
    missing_mods = [m for m in collection_mods if m["mod_id"] not in installed_ids]

    win = Adw.Window(transient_for=window, modal=True)
    win.set_title(
        f"{profile_name} — {len(installed_mods)}/{len(collection_mods)} installed"
    )
    win.set_default_size(540, 680)

    toolbar_view = Adw.ToolbarView()
    toolbar_view.add_top_bar(Adw.HeaderBar())

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    def _make_section(label_text: str, mods: list, css_class: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(4)

        header = Gtk.Label(label=label_text)
        header.set_xalign(0)
        header.add_css_class("heading")
        header.set_margin_bottom(6)
        box.append(header)

        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        for mod in sorted(mods, key=lambda m: m["name"].lower()):
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)

            icon = Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic" if css_class == "success" else "dialog-warning-symbolic"
            )
            icon.add_css_class(css_class)
            row_box.append(icon)

            name_label = Gtk.Label(label=mod["name"])
            name_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name_label.set_hexpand(True)
            name_label.set_xalign(0)
            row_box.append(name_label)

            if mod.get("optional"):
                opt = Gtk.Label(label="optional")
                opt.add_css_class("dim-label")
                opt.add_css_class("caption")
                row_box.append(opt)

            if game_domain:
                uri = f"https://www.nexusmods.com/{game_domain}/mods/{mod['mod_id']}"
                link_btn = Gtk.LinkButton(uri=uri, label="Open")
                link_btn.set_valign(Gtk.Align.CENTER)
                row_box.append(link_btn)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            listbox.append(row)

        box.append(listbox)
        return box

    if missing_mods:
        outer.append(_make_section(
            f"Missing ({len(missing_mods)})", missing_mods, "warning"
        ))
    if installed_mods:
        outer.append(_make_section(
            f"Installed ({len(installed_mods)})", installed_mods, "success"
        ))

    scroll = Gtk.ScrolledWindow()
    scroll.set_child(outer)
    scroll.set_vexpand(True)
    toolbar_view.set_content(scroll)
    win.set_content(toolbar_view)
    win.present()
