"""Help dialog for the mod manager."""

import gi
gi.require_version("Adw", "1")
from gi.repository import Adw


def show_help_dialog(win):
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading="How to use the Mod Manager",
        body=(
            "<b>Installed Mods panel (left)</b>\n"
            "Shows all mods tracked by the manager. "
            "Check/uncheck a mod to enable or disable it (toggles its plugin in the load order).\n\n"
            "<b>Load Order panel (right)</b>\n"
            "Lists all active plugins in the order the game loads them. "
            "Drag rows to reorder. Click <b>Save Order</b> to write the new order — "
            "you must save or your changes will be lost on close.\n\n"
            "<b>+ Install</b>\n"
            "Opens a file picker. Select one or more .zip / .7z / .rar archives. "
            "Each archive is extracted and its files are placed in the correct Data/ folder automatically.\n\n"
            "<b>Setup SE</b>\n"
            "Creates a launch script for the Script Extender (SFSE/SKSE/F4SE). "
            "After clicking, copy the displayed text into Steam → game Properties → Launch Options.\n\n"
            "<b>Check</b>\n"
            "Verifies that the game folder and Script Extender files exist at the expected paths.\n\n"
            "<b>SE Plugin</b> tag in mod list\n"
            "Mods shown with this tag are DLL plugins found in the SE plugins folder. "
            "They were not installed through this manager — remove them manually if needed.\n\n"
            "<b>NXM URL</b> (experimental)\n"
            'Click "NXM URL", paste an <tt>nxm://</tt> link from Nexus Mods. '
            "Requires a free Nexus API key (nexusmods.com → Account → API Keys).\n\n"
            '<a href="https://github.com/pyromaster/linux-sfse-modlauncher">'
            "GitHub Repository</a>"
        ),
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("ok", "Got it")
    dialog.present()
