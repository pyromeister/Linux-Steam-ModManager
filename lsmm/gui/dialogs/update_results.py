import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


def show_update_results(window, updates: list, errors: list):
    if not updates and not errors:
        window._toast("All Nexus mods are up to date")
        return

    dialog = Adw.MessageDialog(
        transient_for=window,
        heading=f"Updates available: {len(updates)}" if updates else "Update Check",
    )

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(120)
    scroll.set_max_content_height(320)

    list_box = Gtk.ListBox()
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    list_box.add_css_class("boxed-list")

    for row_data in updates:
        name, new_ver = row_data[0], row_data[2]
        row = Adw.ActionRow()
        row.set_title(name)
        row.set_subtitle(f"→  {new_ver}")
        list_box.append(row)

    if errors:
        for err in errors:
            row = Adw.ActionRow()
            row.set_title(f"⚠  {err}")
            row.add_css_class("error")
            list_box.append(row)

    scroll.set_child(list_box)
    dialog.set_extra_child(scroll)

    dialog.add_response("close", "Close")
    dialog.set_default_response("close")

    if updates:
        dialog.add_response("update_all", "Update All")
        dialog.set_response_appearance("update_all", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, response):
            if response == "update_all":
                from lsmm.gui.handlers.updates import update_all_async
                update_all_async(window, updates)

        dialog.connect("response", on_response)

    dialog.present()
