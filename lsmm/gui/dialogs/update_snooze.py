import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.config import set_update_snooze


def show_update_snooze_dialog(window, tag: str, release_url: str):
    dialog = Adw.MessageDialog(
        transient_for=window,
        heading=f"Update available: {tag}",
        body="A new version of Linux Steam ModManager is ready.\nChoose when to be reminded again.",
    )

    def _open_release(_btn):
        Gtk.UriLauncher.new(release_url).launch(window, None, None, None)
        dialog.close()

    update_btn = Gtk.Button(label="Update Now")
    update_btn.add_css_class("suggested-action")
    update_btn.connect("clicked", _open_release)

    dialog.add_response("day",   "Remind in 1 day")
    dialog.add_response("week",  "Remind in 7 days")
    dialog.add_response("never", "Don't remind again")
    dialog.add_response("now",   "Update Now")
    dialog.set_response_appearance("now", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response("day")

    def _on_response(_d, response):
        if response == "now":
            Gtk.UriLauncher.new(release_url).launch(window, None, None, None)
        elif response == "day":
            set_update_snooze(1, tag)
        elif response == "week":
            set_update_snooze(7, tag)
        elif response == "never":
            set_update_snooze(None, tag)

    dialog.connect("response", _on_response)
    dialog.present()
