import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib


def show_conflict_dialog(
    window,
    conflicts: list,
    mod_name: str,
    event: threading.Event,
    result: list,
):
    shown = conflicts[:6]
    lines = "\n".join(
        f"  • <tt>{GLib.markup_escape_text(rel)}</tt>\n"
        f"    owned by <b>{GLib.markup_escape_text(owner)}</b>"
        for rel, owner in shown
    )
    body = f"<b>{mod_name}</b> would overwrite {len(conflicts)} file(s) from other mods:\n\n{lines}"
    if len(conflicts) > 6:
        body += f"\n  … and {len(conflicts) - 6} more"

    dialog = Adw.MessageDialog(
        transient_for=window,
        heading="Mod Conflict Detected",
        body=body,
    )
    dialog.set_body_use_markup(True)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("overwrite", "Install Anyway")
    dialog.set_response_appearance("overwrite", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def on_response(_d, r):
        result[0] = r == "overwrite"
        event.set()

    dialog.connect("response", on_response)
    dialog.present()
