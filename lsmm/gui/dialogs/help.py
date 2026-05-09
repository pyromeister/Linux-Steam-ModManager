"""Help / About dialog for the mod manager."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.version import APP_VERSION


def build_help_panel(win) -> Gtk.ScrolledWindow:
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    outer.set_halign(Gtk.Align.CENTER)
    outer.set_margin_top(28)
    outer.set_margin_bottom(24)
    outer.set_margin_start(20)
    outer.set_margin_end(20)

    # App icon
    icon = Gtk.Image.new_from_icon_name("input-gaming-symbolic")
    icon.set_pixel_size(72)
    icon.set_margin_bottom(14)
    outer.append(icon)

    # App name
    name_lbl = Gtk.Label(label="Linux Steam ModManager")
    name_lbl.add_css_class("title-1")
    name_lbl.set_margin_bottom(8)
    outer.append(name_lbl)

    # Version pill
    ver_box = Gtk.Box()
    ver_box.set_halign(Gtk.Align.CENTER)
    ver_box.set_margin_bottom(12)
    ver_box.add_css_class("card")
    ver_lbl = Gtk.Label(label=f"v{APP_VERSION}")
    ver_lbl.add_css_class("caption")
    ver_lbl.add_css_class("dim-label")
    ver_lbl.set_margin_top(3)
    ver_lbl.set_margin_bottom(3)
    ver_lbl.set_margin_start(10)
    ver_lbl.set_margin_end(10)
    ver_box.append(ver_lbl)
    outer.append(ver_box)

    # Description
    desc_lbl = Gtk.Label(
        label="Native GTK4 mod manager for Steam games on Linux and Steam Deck.\n"
              "Handles download, install, enable/disable and load order."
    )
    desc_lbl.set_wrap(True)
    desc_lbl.set_max_width_chars(48)
    desc_lbl.set_justify(Gtk.Justification.CENTER)
    desc_lbl.add_css_class("dim-label")
    desc_lbl.set_margin_bottom(20)
    outer.append(desc_lbl)

    # Link buttons row
    links_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    links_box.set_halign(Gtk.Align.CENTER)
    links_box.set_margin_bottom(28)
    for label, url in [
        ("GitHub", "https://github.com/pyromeister/Linux-Steam-ModManager"),
        ("Issues", "https://github.com/pyromeister/Linux-Steam-ModManager/issues"),
    ]:
        btn = Gtk.Button(label=label)
        btn.add_css_class("pill")
        _u = url
        btn.connect("clicked", lambda b, u=_u: Gtk.UriLauncher.new(u).launch(win, None, None, None))
        links_box.append(btn)
    outer.append(links_box)

    # How to use
    how_lbl = Gtk.Label(label="How to use")
    how_lbl.add_css_class("heading")
    how_lbl.set_xalign(0)
    how_lbl.set_margin_bottom(8)
    outer.append(how_lbl)

    how_box = Gtk.ListBox()
    how_box.set_selection_mode(Gtk.SelectionMode.NONE)
    how_box.add_css_class("boxed-list")
    how_box.set_margin_bottom(8)

    for title, subtitle in [
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
        ("Custom game profiles",
         "Drop a &lt;game&gt;.json file into ~/.config/linux-mod-manager/games/ "
         "to add a game or override a bundled profile."),
    ]:
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_subtitle(subtitle)
        how_box.append(row)

    outer.append(how_box)
    scroll.set_child(outer)
    return scroll


def _populate_help_page(page, win):
    about_group = Adw.PreferencesGroup()
    about_group.set_title("About")
    page.add(about_group)

    app_row = Adw.ActionRow()
    app_row.set_title("Linux Steam ModManager")
    app_row.set_subtitle(f"Version {APP_VERSION} · Mod manager for Steam games on Linux and Steam Deck")
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
