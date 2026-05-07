"""
GTK4 + libadwaita GUI for Linux Steam ModManager.
Entry point: ModManagerApp wraps ModManagerWindow.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Gio


def _install_log_filter() -> None:
    # Suppress the "gtk-application-prefer-dark-theme" warning that fires when
    # the system gtk-4.0/settings.ini still contains that deprecated key.
    # This app uses AdwStyleManager correctly; the warning is a false positive.
    def _filter(domain, level, message, data):
        if "gtk-application-prefer-dark-theme" not in (message or ""):
            GLib.log_default_handler(domain, level, message, None)
    GLib.log_set_handler("Adwaita", GLib.LogLevelFlags.LEVEL_WARNING, _filter, None)


ROOT = Path(__file__).parent.parent.parent

from lsmm.core.config import LOG_PATH
from lsmm.gui.window import ModManagerWindow


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


# ── Application ───────────────────────────────────────────────────────────────

class ModManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.pyromeister.lsmm",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._window: ModManagerWindow | None = None
        self._pending_nxm_for_activate: str | None = None
        self.connect("activate", self._on_activate)
        self.connect("command-line", self._on_command_line)

    def _on_activate(self, app):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        assets_dir = ROOT / "assets"
        if assets_dir.exists():
            display = Gdk.Display.get_default()
            Gtk.IconTheme.get_for_display(display).add_search_path(str(assets_dir))
            css_file = assets_dir / "style.css"
            if css_file.exists():
                provider = Gtk.CssProvider()
                provider.load_from_path(str(css_file))
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        if self._window is None:
            self._window = ModManagerWindow(app, pending_nxm=self._pending_nxm_for_activate)
            self._pending_nxm_for_activate = None
            self._window.set_icon_name("lsmm")
        self._window.present()

    def _on_command_line(self, app, command_line):
        args = command_line.get_arguments()
        nxm_url = next((a for a in args[1:] if a.lower().startswith("nxm://")), None)
        already_running = self._window is not None
        if not already_running:
            self._pending_nxm_for_activate = nxm_url
        self.activate()
        # Only call handle_nxm_url if the window was already open — otherwise
        # _pending_nxm_for_activate handles it to avoid processing the URL twice.
        if nxm_url and already_running and self._window:
            self._window.handle_nxm_url(nxm_url)
        return 0


def main():
    _setup_logging()
    _install_log_filter()
    app = ModManagerApp()
    app.run(sys.argv)
