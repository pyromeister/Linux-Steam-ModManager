import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango


class ModRow(Gtk.ListBoxRow):
    def __init__(self, mod: dict, on_toggle):
        super().__init__()
        self.mod_name = mod["name"]

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(5)
        box.set_margin_bottom(5)
        self.set_child(box)

        check = Gtk.CheckButton()
        check.set_active(mod["active"])
        check.set_valign(Gtk.Align.CENTER)
        check.connect("toggled", lambda btn: on_toggle(self.mod_name, btn.get_active()))
        box.append(check)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        label_box.set_hexpand(True)
        label_box.set_valign(Gtk.Align.CENTER)
        box.append(label_box)

        name_label = Gtk.Label(label=mod["name"])
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        label_box.append(name_label)

        kind = mod.get("kind")
        if kind in ("se_plugin", "framework", "unmanaged"):
            if kind == "framework":
                sub_text = "Framework (not tracked)" if mod.get("untracked") else "Framework"
            elif kind == "unmanaged":
                sub_text = "Unmanaged (not installed via LSMM)"
            else:
                sub_text = "SE Plugin"
            sub = Gtk.Label(label=sub_text)
            sub.set_xalign(0)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            label_box.append(sub)
