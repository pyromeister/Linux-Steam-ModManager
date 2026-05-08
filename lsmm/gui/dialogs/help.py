"""Help / About dialog for the mod manager."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


def _try_get_version() -> str:
    try:
        from importlib.metadata import version
        return version("lsmm")
    except Exception:
        return ""


def show_help_dialog(win):
    dialog = Adw.PreferencesDialog()
    dialog.set_title("Help & About")

    page = Adw.PreferencesPage()
    page.set_title("Linux Steam ModManager")
    page.set_icon_name("help-about-symbolic")
    dialog.add(page)

    # ── About ─────────────────────────────────────────────────────────────────
    about_group = Adw.PreferencesGroup()
    about_group.set_title("About")
    page.add(about_group)

    app_row = Adw.ActionRow()
    app_row.set_title("Linux Steam ModManager")
    ver = _try_get_version()
    app_row.set_subtitle(f"Version {ver}" if ver else "Mod manager for Steam games on Linux and Steam Deck")
    about_group.add(app_row)

    for label, url in [
        ("GitHub Repository", "https://github.com/pyromeister/Linux-Steam-ModManager"),
        ("Report an Issue", "https://github.com/pyromeister/Linux-Steam-ModManager/issues"),
    ]:
        row = Adw.ActionRow()
        row.set_title(label)
        row.set_activatable(True)
        row.add_suffix(Gtk.Image.new_from_icon_name("adw-external-link-symbolic"))
        _url = url
        row.connect("activated", lambda r, u=_url: Gtk.UriLauncher.new(u).launch(win, None, None, None))
        about_group.add(row)

    # ── How to use ────────────────────────────────────────────────────────────
    usage_group = Adw.PreferencesGroup()
    usage_group.set_title("How to use")
    page.add(usage_group)

    sections = [
        ("Mods tab", "Shows all tracked mods. Toggle the checkbox to enable or disable a mod."),
        ("Load Order tab",
         "Lists active plugins in load order. Drag rows to reorder. "
         "Click Save Order — unsaved changes are lost on close."),
        ("Profiles tab",
         "Save the current mod selection as a named profile. Load a profile to restore "
         "a previous mod set and load order."),
        ("Mod Engine tab",
         "Download and configure the Script Extender (SFSE/SKSE/F4SE) or BepInEx. "
         "After setup, copy the shown launch option into Steam → game Properties → Launch Options."),
        ("+ Install",
         "Select one or more .zip / .7z / .rar archives. "
         "Files are extracted and placed in the game's Data/ folder automatically."),
        ("Import from Nexus…",
         "Paste an nxm:// link from the Nexus Mods website. "
         "Requires a free API key (nexusmods.com → Account → API Keys)."),
        ("Check (header)",
         "Verifies that the game folder and Script Extender files exist at the expected paths."),
        ("Custom game profiles",
         "Drop a <game>.json file into ~/.config/linux-mod-manager/games/ "
         "to add a game or override a bundled profile."),
    ]

    for title, subtitle in sections:
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_subtitle(subtitle)
        usage_group.add(row)

    dialog.present(win)
