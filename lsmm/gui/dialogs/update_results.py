import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from lsmm.core.nexus import version_key as _version_key, filter_changelogs as _filter_changelogs


def _show_changelog_dialog(parent, mod_name: str, new_ver: str, changelogs: dict, on_confirm):
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading=f"Update {mod_name}",
        body=f"New version: {new_ver}",
    )

    if changelogs:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        expander = Gtk.Expander(label="Changelog")
        expander.set_expanded(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(240)

        label = Gtk.Label()
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_margin_start(8)
        label.set_margin_end(8)
        label.set_margin_top(4)
        label.set_margin_bottom(4)

        text_parts = []
        for ver in sorted(changelogs, key=_version_key, reverse=True):
            text_parts.append(f"<b>{ver}</b>\n{changelogs[ver]}")
        label.set_markup("\n\n".join(text_parts))

        scroll.set_child(label)
        expander.set_child(scroll)
        outer.append(expander)
        dialog.set_extra_child(outer)

    dialog.add_response("cancel", "Cancel")
    dialog.add_response("update", "Update")
    dialog.set_default_response("update")
    dialog.set_response_appearance("update", Adw.ResponseAppearance.SUGGESTED)

    def on_response(_d, response):
        if response == "update":
            on_confirm()

    dialog.connect("response", on_response)
    dialog.present()


def _fetch_and_confirm(parent, row_data, api_key: str, on_confirm):
    mod_name, _old_fid, new_ver, game_domain, mod_id, new_file_id = row_data[:6]
    installed_version = row_data[6] if len(row_data) > 6 else ""

    spinner = Gtk.Spinner()
    spinner.start()

    loading_dialog = Adw.MessageDialog(
        transient_for=parent,
        heading=f"Loading changelog for {mod_name}…",
    )
    loading_dialog.set_extra_child(spinner)
    loading_dialog.add_response("cancel_load", "Cancel")
    loading_dialog.present()

    cancelled = [False]

    def on_loading_response(_d, response):
        cancelled[0] = True

    loading_dialog.connect("response", on_loading_response)

    def fetch():
        from lsmm.core.nexus import get_mod_changelogs
        changelogs = get_mod_changelogs(game_domain, mod_id, api_key)
        filtered = _filter_changelogs(changelogs, installed_version)

        def show():
            if cancelled[0]:
                return
            loading_dialog.close()
            _show_changelog_dialog(parent, mod_name, new_ver, filtered, on_confirm)

        GLib.idle_add(show)

    threading.Thread(target=fetch, daemon=True).start()


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

    from lsmm.core.config import get_nexus_api_key
    api_key = get_nexus_api_key()

    for row_data in updates:
        name, new_ver = row_data[0], row_data[2]
        row = Adw.ActionRow()
        row.set_title(name)
        row.set_subtitle(f"→  {new_ver}")

        update_btn = Gtk.Button(label="Update")
        update_btn.set_valign(Gtk.Align.CENTER)
        update_btn.add_css_class("suggested-action")

        captured = row_data

        def on_update_clicked(_btn, rd=captured):
            def do_update():
                from lsmm.gui.handlers.updates import update_all_async
                update_all_async(window, [rd])

            _fetch_and_confirm(dialog, rd, api_key, do_update)

        update_btn.connect("clicked", on_update_clicked)
        row.add_suffix(update_btn)
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
