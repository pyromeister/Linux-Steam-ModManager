import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.config import save_nexus_api_key


def show_api_key_dialog(parent, nxm_callback=None):
    """Show dialog to enter/save a Nexus API key. Calls nxm_callback() after saving if provided."""
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading="Nexus API Key Required",
        body="Get your key at nexusmods.com → Account → API Keys:",
    )
    entry = Gtk.Entry()
    entry.set_placeholder_text("Your Nexus API key")
    entry.set_margin_start(16)
    entry.set_margin_end(16)
    entry.set_margin_bottom(8)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save Key")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

    def on_response(d, r):
        if r == "save":
            key = entry.get_text().strip()
            if key:
                save_nexus_api_key(key)
                if nxm_callback:
                    nxm_callback()

    dialog.connect("response", on_response)
    dialog.present()


def show_nxm_api_key_hint(parent):
    """Show one-time hint dialog for NXM URL flow when no API key is set."""
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading="Nexus API Key Required",
        body=(
            "A Nexus API key is required to use Mod Manager Download links.\n"
            "Get it at nexusmods.com → Account → API Keys.\n\n"
            "After saving, click Mod Manager Download in your browser again."
        ),
    )
    entry = Gtk.Entry()
    entry.set_placeholder_text("Your Nexus API key")
    entry.set_activates_default(True)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save Key")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("cancel")

    def _on_response(_dlg, response):
        if response == "save":
            key = entry.get_text().strip()
            if key:
                save_nexus_api_key(key)

    dialog.connect("response", _on_response)
    dialog.present()
