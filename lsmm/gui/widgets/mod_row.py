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
        box.set_margin_top(7)
        box.set_margin_bottom(7)
        self.set_child(box)

        self._check = Gtk.CheckButton()
        self._check.set_active(mod["active"])
        self._check.set_valign(Gtk.Align.CENTER)
        self._check.connect("toggled", lambda btn: on_toggle(self.mod_name, btn.get_active()))
        box.append(self._check)

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

        # Right-side metadata: link · size · version (left→right)
        nexus = mod.get("nexus")
        if nexus:
            mod_id = nexus.get("mod_id")
            game_domain = nexus.get("game_domain")
            if mod_id and game_domain:
                link = Gtk.LinkButton.new_with_label(
                    f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}",
                    f"#{mod_id}",
                )
                link.set_valign(Gtk.Align.CENTER)
                link.add_css_class("caption")
                link.set_has_frame(False)
                box.append(link)

            size_kb = nexus.get("size_kb")
            if size_kb:
                size_lbl = Gtk.Label(label=f"{size_kb / 1024:.2f} MB")
                size_lbl.set_valign(Gtk.Align.CENTER)
                size_lbl.add_css_class("dim-label")
                size_lbl.add_css_class("caption")
                box.append(size_lbl)

            version = nexus.get("version")
            if version:
                ver_chip = Gtk.Label(label=f"v{version}")
                ver_chip.add_css_class("dim-label")
                ver_chip.add_css_class("caption")
                ver_chip.set_valign(Gtk.Align.CENTER)
                box.append(ver_chip)

    def toggle(self) -> None:
        self._check.set_active(not self._check.get_active())


class PendingModRow(Gtk.ListBoxRow):
    """Row for a collection mod that is not yet installed."""

    def __init__(self, mod: dict, game_domain: str):
        super().__init__()
        self.mod_name = mod["name"]

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(7)
        box.set_margin_bottom(7)
        self.set_child(box)

        icon = Gtk.Image.new_from_icon_name("folder-download-symbolic")
        icon.add_css_class("dim-label")
        icon.set_valign(Gtk.Align.CENTER)
        box.append(icon)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        label_box.set_hexpand(True)
        label_box.set_valign(Gtk.Align.CENTER)
        box.append(label_box)

        name_label = Gtk.Label(label=mod["name"])
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.add_css_class("dim-label")
        label_box.append(name_label)

        if mod.get("optional"):
            opt = Gtk.Label(label="optional")
            opt.set_xalign(0)
            opt.add_css_class("dim-label")
            opt.add_css_class("caption")
            label_box.append(opt)

        if game_domain and mod.get("mod_id"):
            uri = f"https://www.nexusmods.com/{game_domain}/mods/{mod['mod_id']}"
            link_btn = Gtk.LinkButton(uri=uri, label="Open on Nexus")
            link_btn.set_valign(Gtk.Align.CENTER)
            link_btn.add_css_class("caption")
            box.append(link_btn)
