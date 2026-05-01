import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw


def show_update_results(window, updates: list, errors: list):
    if not updates and not errors:
        window._toast("All Nexus mods are up to date")
        return

    lines = []
    if updates:
        lines.append("<b>Updates available:</b>")
        for row in updates:
            name, new_ver = row[0], row[2]
            lines.append(f"  • {name}  →  {new_ver}")
    if errors:
        if lines:
            lines.append("")
        lines.append("<b>Errors:</b>")
        for e in errors:
            lines.append(f"  • {e}")

    dialog = Adw.MessageDialog(transient_for=window, heading="Update Check")
    dialog.set_body_use_markup(True)
    dialog.set_body("\n".join(lines))
    dialog.add_response("ok", "OK")
    dialog.set_default_response("ok")

    if updates:
        dialog.add_response("update_all", "Update All")
        dialog.set_response_appearance("update_all", Adw.ResponseAppearance.SUGGESTED)

        def on_response(d, response):
            if response == "update_all":
                from lsmm.gui.handlers.updates import update_all_async
                update_all_async(window, updates)

        dialog.connect("response", on_response)

    dialog.present()
