"""ModManagerWindow — main application window."""

import re
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Gio

from lsmm.core.updater import check_for_update
from lsmm.core.config import (
    get_steam_root, get_steam_candidates,
    get_nexus_api_key, is_update_snoozed,
)
from lsmm.core.utils import (
    load_engine as _load_engine,
    available_games as _available_games,
    find_game_by_nexus_domain as _find_game_by_nexus_domain,
)
from lsmm.gui.widgets.mod_row import ModRow
from lsmm.gui.handlers.install import install_batch, do_uninstall
from lsmm.gui.handlers.nxm import do_nxm_import
from lsmm.gui.handlers.updates import do_check_updates
from lsmm.gui.handlers.collection import rebuild_profiles_popover
from lsmm.gui.handlers.games import build_games_panel, refresh_games
from lsmm.gui.handlers.load_order import build_load_order_panel, refresh_load_order
from lsmm.gui.handlers import setup as setup_handler
from lsmm.core import profiles as _prof
from lsmm.gui.dialogs.api_key import show_api_key_dialog, show_nxm_api_key_hint
from lsmm.gui.dialogs.steam_path import show_steam_path_dialog
from lsmm.gui.dialogs.first_run import show_first_run_wizard
from lsmm.gui.dialogs.help import show_help_dialog
from lsmm.gui.dialogs.settings import show_settings_dialog
from lsmm.gui.dialogs.update_snooze import show_update_snooze_dialog


def _list_store_from_filter(f: Gtk.FileFilter) -> Gio.ListStore:
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    return store


class _TabRef:
    """Adapter replacing Gtk.Popover in rebuild_profiles_popover for the Profiles tab.
    popdown() triggers a tab content refresh instead of dismissing a popover."""

    def __init__(self, refresh_fn):
        self._refresh = refresh_fn

    def popdown(self):
        self._refresh()


# ── Main window ───────────────────────────────────────────────────────────────

class ModManagerWindow(Adw.ApplicationWindow):
    def __init__(self, app, pending_nxm: str | None = None):
        super().__init__(application=app)
        self.set_title("Linux Steam ModManager")
        self.set_default_size(1280, 800)

        self.engine = None
        self.games = _available_games()
        self._installing = False
        self._game_slug = None
        self._pending_nxm: str | None = pending_nxm

        self._build_ui()
        self._update_setup_btn()
        self._update_action_sensitivity()
        self._refresh_mods()
        GLib.idle_add(self._init_steam_path)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root)

        # ── Header bar ────────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        root.append(header)

        check_btn = Gtk.Button(label="Check")
        check_btn.connect("clicked", self._on_check)
        header.pack_end(check_btn)

        self.launch_btn = Gtk.Button(label="▶ Launch")
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.set_tooltip_text("Launch game via Steam")
        self.launch_btn.set_sensitive(False)
        self.launch_btn.connect("clicked", self._on_launch_game)
        header.pack_end(self.launch_btn)

        settings_action = Gio.SimpleAction.new("open-settings", None)
        settings_action.connect("activate", lambda a, p: show_settings_dialog(self))
        self.add_action(settings_action)
        self.get_application().set_accels_for_action("win.open-settings", ["<Ctrl>comma"])

        # ── Body: nav rail + separator + content ──────────────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_vexpand(True)
        root.append(body)

        # ── Nav rail (72px) ───────────────────────────────────────────────────
        nav_rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        nav_rail.set_size_request(72, -1)
        nav_rail.add_css_class("navigation-sidebar")
        body.append(nav_rail)

        # Games flyout
        games_popover = Gtk.Popover()
        games_popover.set_position(Gtk.PositionType.RIGHT)
        games_panel = build_games_panel(self)
        games_panel.set_size_request(260, 480)
        games_popover.set_child(games_panel)
        self.games_list.connect("row-activated", lambda lb, row: games_popover.popdown())

        games_btn = Gtk.MenuButton()
        games_btn.set_popover(games_popover)
        games_btn.set_size_request(-1, 64)
        games_btn.set_direction(Gtk.ArrowType.NONE)
        games_btn.set_tooltip_text("Choose game")
        games_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        games_inner.set_valign(Gtk.Align.CENTER)
        games_inner.append(Gtk.Image.new_from_icon_name("input-gaming-symbolic"))
        games_lbl = Gtk.Label(label="Games")
        games_lbl.add_css_class("caption")
        games_inner.append(games_lbl)
        games_btn.set_child(games_inner)
        nav_rail.append(games_btn)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        nav_rail.append(spacer)

        settings_btn = Gtk.Button()
        settings_btn.set_icon_name("preferences-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.set_size_request(-1, 64)
        settings_btn.connect("clicked", lambda _: show_settings_dialog(self))
        nav_rail.append(settings_btn)

        help_btn = Gtk.Button()
        help_btn.set_icon_name("help-about-symbolic")
        help_btn.set_tooltip_text("Help")
        help_btn.set_size_request(-1, 64)
        help_btn.connect("clicked", lambda _: show_help_dialog(self))
        nav_rail.append(help_btn)

        # ── Separator ─────────────────────────────────────────────────────────
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # ── Content area ──────────────────────────────────────────────────────
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_hexpand(True)
        body.append(content)

        self._view_stack = Adw.ViewStack()
        self._view_stack.set_vexpand(True)
        self._view_stack.add_titled_with_icon(
            self._build_profiles_tab(), "profiles", "Profiles", "contact-new-symbolic"
        )
        self._view_stack.add_titled_with_icon(
            self._build_mod_engine_tab(), "mod-engine", "Mod Engine", "application-x-executable-symbolic"
        )
        self._view_stack.add_titled_with_icon(
            self._build_mods_panel(), "mods", "Mods", "package-x-generic-symbolic"
        )
        self.load_order_panel = build_load_order_panel(self)
        self._lo_page = self._view_stack.add_titled_with_icon(
            self.load_order_panel, "load-order", "Load Order", "view-sort-descending-symbolic"
        )
        self._lo_page.set_visible(False)
        content.append(self._view_stack)

        self._view_switcher_bar = Adw.ViewSwitcherBar()
        self._view_switcher_bar.set_stack(self._view_stack)
        self._view_switcher_bar.set_reveal(True)
        content.append(self._view_switcher_bar)

        # ── Status bar ────────────────────────────────────────────────────────
        status_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.status_label = Gtk.Label(label="Ready")
        self.status_label.add_css_class("dim-label")
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.set_margin_top(4)
        self.status_label.set_xalign(0)
        status_bar.append(self.status_label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_start(12)
        self.progress_bar.set_margin_end(12)
        self.progress_bar.set_margin_bottom(4)
        self.progress_bar.set_visible(False)
        status_bar.append(self.progress_bar)

        content.append(status_bar)
        self._pulse_source_id: int | None = None

        # Populate profiles tab initial state
        self._refresh_profiles_tab()

    # ── Profiles tab ──────────────────────────────────────────────────────────

    def _build_profiles_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._profiles_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._profiles_popover_box.set_margin_start(12)
        self._profiles_popover_box.set_margin_end(12)
        self._profiles_popover_box.set_margin_top(10)
        self._profiles_popover_box.set_margin_bottom(10)
        scroll.set_child(self._profiles_popover_box)
        return scroll

    def _refresh_profiles_tab(self):
        rebuild_profiles_popover(self, _TabRef(self._refresh_profiles_tab))

    # ── Mod Engine tab ────────────────────────────────────────────────────────

    def _build_mod_engine_tab(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._mod_engine_placeholder = Adw.StatusPage()
        self._mod_engine_placeholder.set_icon_name("application-x-executable-symbolic")
        self._mod_engine_placeholder.set_title("No game selected")
        self._mod_engine_placeholder.set_description("Select a game from the Games menu")
        outer.append(self._mod_engine_placeholder)

        self._mod_engine_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._mod_engine_content.set_margin_start(16)
        self._mod_engine_content.set_margin_end(16)
        self._mod_engine_content.set_margin_top(16)
        self._mod_engine_content.set_margin_bottom(16)
        self._mod_engine_content.set_visible(False)

        self._engine_name_label = Gtk.Label()
        self._engine_name_label.add_css_class("heading")
        self._engine_name_label.set_xalign(0)
        self._mod_engine_content.append(self._engine_name_label)

        self._se_status_label = Gtk.Label()
        self._se_status_label.add_css_class("dim-label")
        self._se_status_label.set_xalign(0)
        self._mod_engine_content.append(self._se_status_label)

        self.setup_btn = Gtk.Button()
        self.setup_btn.connect("clicked", self._on_setup_btn)
        self._mod_engine_content.append(self.setup_btn)

        self._ensure_ini_btn = Gtk.Button(label="Ensure INI Settings")
        self._ensure_ini_btn.set_tooltip_text("Add bInvalidateOlderFiles=1 to the game's Custom INI")
        self._ensure_ini_btn.connect("clicked", self._on_ensure_ini)
        self._ensure_ini_btn.set_visible(False)
        self._mod_engine_content.append(self._ensure_ini_btn)

        verify_btn = Gtk.Button(label="Verify Paths")
        verify_btn.set_tooltip_text("Check that game and script extender paths exist")
        verify_btn.connect("clicked", self._on_verify_paths_btn)
        self._mod_engine_content.append(verify_btn)

        outer.append(self._mod_engine_content)
        return outer

    def _get_engine_display(self) -> tuple[str, str]:
        """Return (framework_name, status_text) for the Mod Engine tab."""
        if getattr(self.engine, "has_framework_setup", False):
            fw = getattr(self.engine, "framework_name", "BepInEx")
            installed = self.engine.is_framework_installed()
            return fw, "✓ Installed" if installed else "Not installed"
        se = self.engine.profile.get("script_extender")
        if se:
            paths = getattr(self.engine, "paths", None)
            se_installed = bool(paths and paths.se_loader and paths.se_loader.exists())
            return se.get("name", "Script Extender"), "✓ Installed" if se_installed else "Not installed"
        return "No script extender", ""

    def _refresh_mod_engine_tab(self):
        if not self.engine:
            self._mod_engine_placeholder.set_visible(True)
            self._mod_engine_content.set_visible(False)
            return

        self._mod_engine_placeholder.set_visible(False)
        self._mod_engine_content.set_visible(True)
        name, status = self._get_engine_display()
        self._engine_name_label.set_text(name)
        self._se_status_label.set_text(status)
        self._ensure_ini_btn.set_visible(hasattr(self.engine, "ensure_ini"))
        self._update_setup_btn()

    def _on_ensure_ini(self, _btn):
        if not self.engine or not hasattr(self.engine, "ensure_ini"):
            return
        try:
            self.engine.ensure_ini()
            self._toast("✓ INI settings applied")
        except Exception as e:
            self._toast(f"INI update failed: {e}")

    def _show_verify_warnings(self, warnings: list[str]) -> None:
        if warnings:
            self._toast(f"⚠ {warnings[0]}" + (f" (+{len(warnings)-1} more)" if len(warnings) > 1 else ""))
        else:
            self._toast("✓ All paths verified")

    def _on_verify_paths_btn(self, _btn):
        if not self.engine:
            return
        if hasattr(self.engine, "paths"):
            self._show_verify_warnings(self.engine.paths.verify())
        else:
            self._toast("Verify not supported for this engine")

    # ── Progress bar helpers ──────────────────────────────────────────────────

    def _progress_start_pulse(self) -> None:
        self.progress_bar.set_visible(True)
        self.progress_bar.set_fraction(0.0)
        if self._pulse_source_id is None:
            self._pulse_source_id = GLib.timeout_add(80, self._on_pulse_tick)

    def _on_pulse_tick(self) -> bool:
        self.progress_bar.pulse()
        return True

    def _progress_set(self, fraction: float) -> None:
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None
        self.progress_bar.set_visible(True)
        self.progress_bar.set_fraction(max(0.0, min(1.0, fraction)))

    def _progress_done(self) -> None:
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_visible(False)

    # ── Game list ─────────────────────────────────────────────────────────────

    def _refresh_games(self):
        refresh_games(self)

    def _iter_game_rows(self):
        row = self.games_list.get_first_child()
        while row:
            if isinstance(row, Gtk.ListBoxRow):
                yield row
            row = row.get_next_sibling()

    # ── Game selection ────────────────────────────────────────────────────────

    def _select_game(self, slug: str):
        name = next((n for s, n in self.games if s == slug), slug)
        try:
            self.engine = _load_engine(slug)
        except Exception as e:
            self._toast(f"Failed to load engine: {e}")
            return

        self._game_slug = slug
        self.set_title(f"Linux Steam ModManager — {name}")
        self._update_load_order_panel()
        self._refresh_mods()
        self._refresh_load_order()
        self._update_action_sensitivity()
        self.launch_btn.set_sensitive(bool(self.engine.profile.get("steam_app_id")))
        self._refresh_mod_engine_tab()
        GLib.idle_add(self._refresh_profiles_tab)

        paths = getattr(self.engine, "paths", None)
        if paths and hasattr(paths, "proton_prefix") and not paths.proton_prefix.exists():
            self._toast(f"{name}: launch the game once via Steam to create the Proton prefix")
        if paths and getattr(paths, "on_microsd", False):
            self._toast(f"{name}: game is on microSD — expect slower load times")

    # ── Steam path setup ──────────────────────────────────────────────────────

    def _init_steam_path(self):
        self._refresh_games()
        self.games_list.grab_focus()
        if get_steam_root() is None and get_nexus_api_key() is None:
            show_first_run_wizard(self)
        elif get_steam_root() is None:
            show_steam_path_dialog(self, get_steam_candidates())
        if self._pending_nxm:
            nxm_url = self._pending_nxm
            self._pending_nxm = None
            GLib.idle_add(self._handle_startup_nxm, nxm_url)

    def _update_load_order_panel(self):
        has_lo = self.engine.has_load_order
        self._lo_page.set_visible(has_lo)

    # ── Mods panel ────────────────────────────────────────────────────────────

    def _build_mods_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_size_request(680, -1)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_top(12)
        header_box.set_margin_bottom(8)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)

        header_label = Gtk.Label(label="Installed Mods")
        header_label.add_css_class("heading")
        header_label.set_hexpand(True)
        header_label.set_xalign(0)
        header_box.append(header_label)

        self.active_set_label = Gtk.Label(label="No active set")
        self.active_set_label.add_css_class("dim-label")
        self.active_set_label.add_css_class("caption")
        self.active_set_label.set_valign(Gtk.Align.CENTER)
        header_box.append(self.active_set_label)

        panel.append(header_box)

        self.mods_search = Gtk.SearchEntry()
        self.mods_search.set_placeholder_text("Search mods…")
        self.mods_search.set_margin_start(12)
        self.mods_search.set_margin_end(12)
        self.mods_search.set_margin_bottom(8)
        self.mods_search.connect("search-changed", self._on_mods_search_changed)
        panel.append(self.mods_search)

        self.mods_content_stack = Gtk.Stack()
        self.mods_content_stack.set_vexpand(True)
        self.mods_content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        empty_status = Adw.StatusPage()
        empty_status.set_icon_name("package-x-generic-symbolic")
        empty_status.set_title("No mods installed")
        empty_status.set_description("Select a game and click + Install to add mods")
        self.mods_content_stack.add_named(empty_status, "empty")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.mods_list = Gtk.ListBox()
        self.mods_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.mods_list.add_css_class("boxed-list")
        self.mods_list.set_margin_start(12)
        self.mods_list.set_margin_end(12)
        self.mods_list.set_filter_func(self._mods_filter_func)
        scroll.set_child(self.mods_list)
        self.mods_content_stack.add_named(scroll, "list")

        panel.append(self.mods_content_stack)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_start(12)
        btn_box.set_margin_end(12)
        btn_box.set_margin_top(12)
        btn_box.set_margin_bottom(12)

        self.install_btn = Gtk.Button(label="+ Install")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.connect("clicked", self._on_install)
        self.install_btn.set_hexpand(True)
        self.install_btn.set_sensitive(False)
        btn_box.append(self.install_btn)

        self.uninstall_btn = Gtk.Button(label="- Uninstall")
        self.uninstall_btn.add_css_class("destructive-action")
        self.uninstall_btn.connect("clicked", self._on_uninstall)
        self.uninstall_btn.set_hexpand(True)
        self.uninstall_btn.set_sensitive(False)
        btn_box.append(self.uninstall_btn)

        self.nxm_btn = Gtk.Button(label="Import from Nexus…")
        self.nxm_btn.set_tooltip_text("Import mod via Nexus nxm:// link")
        self.nxm_btn.connect("clicked", self._on_nxm_import)
        self.nxm_btn.set_hexpand(True)
        self.nxm_btn.set_sensitive(False)
        btn_box.append(self.nxm_btn)

        self.update_btn = Gtk.Button(label="Check Updates")
        self.update_btn.set_tooltip_text("Check Nexus Mods for updates to installed mods")
        self.update_btn.connect("clicked", self._on_check_updates)
        self.update_btn.set_hexpand(True)
        self.update_btn.set_sensitive(False)
        btn_box.append(self.update_btn)

        panel.append(btn_box)
        return panel

    # ── Mod list ──────────────────────────────────────────────────────────────

    def _refresh_mods(self):
        while child := self.mods_list.get_first_child():
            self.mods_list.remove(child)

        if not self.engine:
            self.mods_content_stack.set_visible_child_name("empty")
            return

        try:
            mods = self.engine.list_mods()
        except Exception as e:
            self._toast(f"Could not load mod list: {e}")
            self.mods_content_stack.set_visible_child_name("empty")
            return

        if not mods:
            self.mods_content_stack.set_visible_child_name("empty")
            return

        self.mods_content_stack.set_visible_child_name("list")
        for mod in sorted(mods, key=lambda m: m["name"].lower()):
            row = ModRow(mod, self._on_toggle_mod)
            self.mods_list.append(row)

        self._update_active_set_label()

    def _update_active_set_label(self):
        if not self._game_slug:
            self.active_set_label.set_text("No active set")
            return
        name = _prof.get_active(self._game_slug)
        if not name:
            self.active_set_label.set_text("No active set")
            return
        try:
            mods = self.engine.list_mods() if self.engine else []
        except Exception:
            mods = []
        current = [m["name"] for m in mods if m.get("active")]
        dirty = _prof.is_dirty(self._game_slug, name, current)
        self.active_set_label.set_text(f"Set: {name}{'*' if dirty else ''}")

    def _mods_filter_func(self, row: Gtk.ListBoxRow) -> bool:
        query = self.mods_search.get_text().strip().lower()
        if not query:
            return True
        if not isinstance(row, ModRow):
            return True
        return query in row.mod_name.lower()

    def _on_mods_search_changed(self, _entry):
        self.mods_list.invalidate_filter()

    def _on_launch_game(self, _btn):
        if not self.engine:
            return
        app_id = self.engine.profile.get("steam_app_id", "")
        if not app_id:
            self._toast("No Steam App ID for this game")
            return
        import subprocess
        try:
            subprocess.Popen(["xdg-open", f"steam://rungameid/{app_id}"])
            self._toast("Launching via Steam…")
        except Exception as e:
            self._toast(f"Launch failed: {e}")

    def _on_toggle_mod(self, mod_name: str, active: bool):
        def run():
            if active:
                self.engine.enable_mod(mod_name)
            else:
                self.engine.disable_mod(mod_name)
            GLib.idle_add(self._update_active_set_label)
        threading.Thread(target=run, daemon=True).start()

    # ── Install ───────────────────────────────────────────────────────────────

    def _update_action_sensitivity(self):
        has_engine = self.engine is not None
        self.install_btn.set_sensitive(has_engine)
        self.uninstall_btn.set_sensitive(has_engine)
        self.nxm_btn.set_sensitive(has_engine)
        self.update_btn.set_sensitive(has_engine)

    def _on_install(self, _btn):
        if not self.engine:
            return
        dialog = Gtk.FileDialog()
        dialog.set_title("Select mod archives")

        filters = Gtk.FileFilter()
        filters.set_name("Mod archives")
        filters.add_pattern("*.zip")
        filters.add_pattern("*.7z")
        filters.add_pattern("*.rar")
        dialog.set_filters(_list_store_from_filter(filters))
        dialog.open_multiple(self, None, self._on_files_selected)

    def _on_files_selected(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except Exception:
            return
        paths = [Path(files.get_item(i).get_path()) for i in range(files.get_n_items())]
        if not paths:
            return
        install_batch(self, paths)

    # ── Uninstall ─────────────────────────────────────────────────────────────

    def _on_uninstall(self, _btn):
        if not self.engine:
            return
        row = self.mods_list.get_selected_row()
        if not row or not isinstance(row, ModRow):
            self._toast("Select a mod to uninstall")
            return

        mod_name = row.mod_name
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Uninstall mod?",
            body=f'This will remove all files for "{mod_name}".',
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("uninstall", "Uninstall")
        dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda d, r: self._do_uninstall(mod_name) if r == "uninstall" else None)
        dialog.present()

    def _do_uninstall(self, mod_name: str):
        do_uninstall(self, mod_name)

    # ── Load order ────────────────────────────────────────────────────────────

    def _refresh_load_order(self):
        refresh_load_order(self)

    # ── NXM import ────────────────────────────────────────────────────────────

    def _handle_startup_nxm(self, url: str) -> bool:
        from lsmm.core.nexus import parse_nxm
        parsed = parse_nxm(url)
        if not parsed:
            self._toast(f"Invalid NXM URL: {url[:60]}")
            return GLib.SOURCE_REMOVE

        slug = _find_game_by_nexus_domain(parsed.get("game_domain", ""))
        if slug:
            for row in self._iter_game_rows():
                if getattr(row, "_slug", None) == slug:
                    self.games_list.select_row(row)
                    break
            self._select_game(slug)
        else:
            self._toast(f"No profile for Nexus domain: {parsed.get('game_domain')}")

        api_key = get_nexus_api_key()
        if not api_key:
            show_nxm_api_key_hint(self)
            return GLib.SOURCE_REMOVE

        do_nxm_import(self, url, api_key)
        return GLib.SOURCE_REMOVE

    def handle_nxm_url(self, url: str) -> None:
        """Called by ModManagerApp when an NXM URL arrives in a running instance."""
        self.present()
        GLib.idle_add(self._handle_startup_nxm, url)

    def _on_nxm_import(self, _btn):
        if not self.engine:
            return

        api_key = get_nexus_api_key()
        if not api_key:
            show_api_key_dialog(self, nxm_callback=lambda: self._on_nxm_import(None))
            return

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Import from Nexus Mods",
            body='Paste the nxm:// link (from "Mod Manager Download" on Nexus):',
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("nxm://starfield/mods/.../files/...")
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        entry.set_margin_bottom(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("import", "Import")
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("import")
        dialog.connect(
            "response",
            lambda d, r: do_nxm_import(self, entry.get_text(), api_key) if r == "import" else None,
        )
        dialog.present()

    # ── Update check ──────────────────────────────────────────────────────────

    def _on_check_updates(self, _btn):
        if not self.engine:
            return
        api_key = get_nexus_api_key()
        if not api_key:
            self._toast("Nexus API key not set — open Settings to add one")
            return
        do_check_updates(self, api_key)

    # ── Profiles ──────────────────────────────────────────────────────────────

    def _get_installed_nexus_mod_ids(self, game_slug: str) -> set:
        """Return set of nexus mod_ids installed for this game."""
        from lsmm.core.installer import load_manifest
        manifest = load_manifest()
        ids: set = set()
        for mod_name, entry in manifest.items():
            if entry.get("game") not in (None, game_slug):
                continue
            nexus = entry.get("nexus") or {}
            if nexus.get("mod_id"):
                ids.add(int(nexus["mod_id"]))
                continue
            hit = re.search(r"-(\d{4,})-\d+(?:-\d+)*$", mod_name)
            if hit:
                ids.add(int(hit.group(1)))
        if self.engine and hasattr(self.engine, "filesystem_nexus_ids"):
            ids |= self.engine.filesystem_nexus_ids()
        return ids

    # ── Header actions ────────────────────────────────────────────────────────

    def _on_check(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return
        if hasattr(self.engine, "verify"):
            self._show_verify_warnings(self.engine.verify())
        elif hasattr(self.engine, "paths"):
            self._show_verify_warnings(self.engine.paths.verify())
        else:
            self._toast("Check not supported for this engine")

    def _update_setup_btn(self):
        if not self.engine:
            self.setup_btn.set_label("Script Extender")
            self.setup_btn.set_sensitive(False)
            self.setup_btn.set_tooltip_text("Select a game first")
            return
        self.setup_btn.set_sensitive(True)
        if getattr(self.engine, "has_framework_setup", False):
            installed = self.engine.is_framework_installed()
            fw = getattr(self.engine, "framework_name", "BepInEx")
            self.setup_btn.set_label(f"{fw} ✓" if installed else f"Install {fw}")
            self.setup_btn.set_tooltip_text(
                f"{fw} is installed" if installed
                else f"Download and install {fw} into the game folder"
            )
        elif self.engine.has_script_extender:
            se = self.engine.profile.get("script_extender", {})
            se_name = se.get("name", "Script Extender")
            paths = getattr(self.engine, "paths", None)
            se_installed = bool(paths and paths.se_loader and paths.se_loader.exists())
            self.setup_btn.set_label(f"{se_name} ✓" if se_installed else se_name)
            self.setup_btn.set_tooltip_text(
                f"{se_name} is installed — click to (re)create the Steam launch wrapper"
                if se_installed else
                f"Download {se_name} and extract to the game folder, then click here to create the launch wrapper"
            )
        else:
            self.setup_btn.set_label("Script Extender")
            self.setup_btn.set_sensitive(False)
            self.setup_btn.set_tooltip_text("No script extender for this game")

    def _on_setup_btn(self, _btn):
        setup_handler.handle_setup_btn(self)

    # ── Update check ──────────────────────────────────────────────────────────

    def _check_for_update(self):
        result = check_for_update()
        if result:
            tag, url = result
            if not is_update_snoozed(tag):
                GLib.idle_add(show_update_snooze_dialog, self, tag, url)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _toast(self, message: str):
        toast = Adw.Toast(title=GLib.markup_escape_text(message))
        self.toast_overlay.add_toast(toast)
