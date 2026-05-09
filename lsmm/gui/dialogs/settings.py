import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.config import (
    get_nexus_api_key, save_nexus_api_key,
    get_steam_root, get_steam_candidates, save_steam_root,
    get_check_updates_on_launch, save_check_updates_on_launch,
)
from lsmm.core.version import APP_VERSION


def build_settings_panel(window) -> Adw.PreferencesPage:
    page = Adw.PreferencesPage()
    page.set_title("Settings")
    page.set_icon_name("preferences-system-symbolic")
    _populate_settings_page(page, window)
    return page




def _populate_settings_page(page, window, dialog=None):
    # ── App ───────────────────────────────────────────────────────────────────
    app_group = Adw.PreferencesGroup()
    app_group.set_title("Application")
    page.add(app_group)

    ver_row = Adw.ActionRow()
    ver_row.set_title("Version")
    ver_row.set_subtitle(APP_VERSION)
    app_group.add(ver_row)

    launch_check_row = Adw.SwitchRow()
    launch_check_row.set_title("Check for updates on launch")
    launch_check_row.set_subtitle("Show notification when a new version is available at startup")
    launch_check_row.set_active(get_check_updates_on_launch())
    launch_check_row.connect(
        "notify::active",
        lambda row, _: save_check_updates_on_launch(row.get_active()),
    )
    app_group.add(launch_check_row)

    # ── Nexus Mods ────────────────────────────────────────────────────────────
    nexus_group = Adw.PreferencesGroup()
    nexus_group.set_title("Nexus Mods")
    page.add(nexus_group)

    api_row = Adw.PasswordEntryRow()
    api_row.set_title("API Key")
    current_key = get_nexus_api_key() or ""
    api_row.set_text(current_key)
    nexus_group.add(api_row)

    save_btn = Gtk.Button(label="Save")
    save_btn.set_valign(Gtk.Align.CENTER)
    save_btn.add_css_class("suggested-action")

    def _save_key(_btn):
        key = api_row.get_text().strip()
        if key:
            save_nexus_api_key(key)
            window._toast("API key saved")
        else:
            window._toast("API key cannot be empty")

    save_btn.connect("clicked", _save_key)
    api_row.add_suffix(save_btn)

    link_row = Adw.ActionRow()
    link_row.set_title("Get a free API key")
    link_row.set_subtitle("nexusmods.com → Account → API keys")
    link_row.set_activatable(True)
    link_row.add_suffix(Gtk.Image.new_from_icon_name("adw-external-link-symbolic"))

    def _open_nexus(_row, *_):
        Gtk.UriLauncher.new(
            "https://www.nexusmods.com/users/myaccount?tab=api"
        ).launch(window, None, None, None)

    link_row.connect("activated", _open_nexus)
    nexus_group.add(link_row)

    # ── Steam ─────────────────────────────────────────────────────────────────
    steam_group = Adw.PreferencesGroup()
    steam_group.set_title("Steam")
    page.add(steam_group)

    steam_row = Adw.ActionRow()
    steam_row.set_title("Steam root")
    root = get_steam_root()
    steam_row.set_subtitle(str(root) if root else "Not detected")
    steam_group.add(steam_row)

    detect_btn = Gtk.Button(label="Auto-detect")
    detect_btn.set_valign(Gtk.Align.CENTER)

    def _detect(_btn):
        candidates = get_steam_candidates()
        if len(candidates) == 1:
            save_steam_root(candidates[0])
            steam_row.set_subtitle(str(candidates[0]))
            window._toast("Steam root updated")
        elif not candidates:
            window._toast("Steam not found on this system")
        else:
            window._toast(f"{len(candidates)} Steam installs found — set path manually")

    detect_btn.connect("clicked", _detect)
    steam_row.add_suffix(detect_btn)

    # ── App Updates ───────────────────────────────────────────────────────────
    updates_group = Adw.PreferencesGroup()
    updates_group.set_title("App Updates")
    page.add(updates_group)

    update_row = Adw.ActionRow()
    update_row.set_title("Check for updates")
    update_row.set_subtitle("Check GitHub for a newer version of Linux Steam ModManager")
    updates_group.add(update_row)

    check_btn = Gtk.Button(label="Check Now")
    check_btn.set_valign(Gtk.Align.CENTER)

    def _check(_btn):
        import threading
        from lsmm.core.updater import check_for_update
        from lsmm.gui.dialogs.update_snooze import show_update_snooze_dialog
        from gi.repository import GLib

        check_btn.set_sensitive(False)
        check_btn.set_label("Checking…")

        def run():
            result = check_for_update()

            def done():
                check_btn.set_sensitive(True)
                check_btn.set_label("Check Now")
                if result:
                    tag, url = result
                    if dialog:
                        dialog.close()
                    show_update_snooze_dialog(window, tag, url)
                else:
                    window._toast("Linux Steam ModManager is up to date")
            GLib.idle_add(done)

        threading.Thread(target=run, daemon=True).start()

    check_btn.connect("clicked", _check)
    update_row.add_suffix(check_btn)
