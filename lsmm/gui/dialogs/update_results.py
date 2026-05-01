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
        for name, _old, new_ver in updates:
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
    dialog.present()
