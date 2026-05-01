"""
GTK4 + libadwaita GUI for Linux Steam ModManager.
Entry point: ModManagerApp wraps ModManagerWindow.
"""

import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk, Gio

ROOT = Path(__file__).parent.parent.parent

from lsmm.core.utils import find_game_by_nexus_domain
from lsmm.gui.window import ModManagerWindow


# ── Application ───────────────────────────────────────────────────────────────

class ModManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.linuxmodmanager",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._window: ModManagerWindow | None = None
        self._pending_nxm_for_activate: str | None = None
        self.connect("activate", self._on_activate)
        self.connect("command-line", self._on_command_line)

    def _on_activate(self, app):
        try:
            settings = Gtk.Settings.get_default()
            if settings is not None:
                settings.reset_property("gtk-application-prefer-dark-theme")
        except Exception:
            pass
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        assets_dir = ROOT / "assets"
        if assets_dir.exists():
            display = Gdk.Display.get_default()
            Gtk.IconTheme.get_for_display(display).add_search_path(str(assets_dir))
        if self._window is None:
            self._window = ModManagerWindow(app, pending_nxm=self._pending_nxm_for_activate)
            self._pending_nxm_for_activate = None
            self._window.set_icon_name("lsmm")
        self._window.present()

    def _on_command_line(self, app, command_line):
        args = command_line.get_arguments()
        nxm_url = next((a for a in args[1:] if a.lower().startswith("nxm://")), None)
        if self._window is None:
            self._pending_nxm_for_activate = nxm_url
        self.activate()
        if nxm_url and self._window:
            self._window.handle_nxm_url(nxm_url)
        return 0


def main():
    app = ModManagerApp()
    app.run(sys.argv)
