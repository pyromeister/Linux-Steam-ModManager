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
    get_check_updates_on_launch,
    get_path_overrides, save_path_overrides,
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

from lsmm.gui.handlers.games import build_games_panel, refresh_games
from lsmm.gui.handlers.load_order import build_load_order_panel, refresh_load_order
from lsmm.gui.handlers import setup as setup_handler
from lsmm.core import profiles as _prof
from lsmm.core.script_extender import fetch_github_latest_tag
from lsmm.gui.dialogs.api_key import show_api_key_dialog, show_nxm_api_key_hint
from lsmm.gui.dialogs.steam_path import show_steam_path_dialog
from lsmm.gui.dialogs.first_run import show_first_run_wizard
from lsmm.gui.dialogs.help import build_help_panel
from lsmm.gui.dialogs.settings import build_settings_panel
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
        self._se_version_cache: dict = {}
        self._se_check_in_flight: set = set()
        self._tracked_cache: dict = {}
        self._tracked_fetch_in_flight: set = set()

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

        self.launch_btn = Gtk.Button(label="▶ Launch")
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.set_tooltip_text("Launch game via Steam")
        self.launch_btn.set_sensitive(False)
        self.launch_btn.connect("clicked", self._on_launch_game)
        header.pack_end(self.launch_btn)

        settings_action = Gio.SimpleAction.new("open-settings", None)
        settings_action.connect(
            "activate",
            lambda a, p: (self._close_games_flyout(), self._content_stack.set_visible_child_name("settings")),
        )
        self.add_action(settings_action)
        self.get_application().set_accels_for_action("win.open-settings", ["<Ctrl>comma"])

        # ── Body: nav rail + separator + content overlay ──────────────────────
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_vexpand(True)
        root.append(body)

        # ── Nav rail (72px) ───────────────────────────────────────────────────
        nav_rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        nav_rail.set_size_request(72, -1)
        nav_rail.add_css_class("navigation-sidebar")
        body.append(nav_rail)

        games_btn = Gtk.Button()
        games_btn.set_size_request(-1, 64)
        games_btn.set_tooltip_text("Choose game")
        games_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        games_inner.set_valign(Gtk.Align.CENTER)
        games_inner.append(Gtk.Image.new_from_icon_name("input-gaming-symbolic"))
        games_lbl = Gtk.Label(label="Games")
        games_lbl.add_css_class("caption")
        games_inner.append(games_lbl)
        games_btn.set_child(games_inner)
        games_btn.connect("clicked", lambda _: self._toggle_games_flyout())
        nav_rail.append(games_btn)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        nav_rail.append(spacer)

        settings_btn = Gtk.Button()
        settings_btn.set_icon_name("preferences-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.set_size_request(-1, 64)
        settings_btn.connect("clicked", lambda _: (
            self._close_games_flyout(),
            self._content_stack.set_visible_child_name("settings"),
        ))
        nav_rail.append(settings_btn)

        help_btn = Gtk.Button()
        help_btn.set_icon_name("help-about-symbolic")
        help_btn.set_tooltip_text("Help")
        help_btn.set_size_request(-1, 64)
        help_btn.connect("clicked", lambda _: (
            self._close_games_flyout(),
            self._content_stack.set_visible_child_name("help"),
        ))
        nav_rail.append(help_btn)

        # ── Separator ─────────────────────────────────────────────────────────
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # ── Content overlay (flyout + main content) ───────────────────────────
        content_overlay = Gtk.Overlay()
        content_overlay.set_hexpand(True)
        body.append(content_overlay)

        # Build games panel before overlay setup (sets win.games_list etc.)
        games_panel = build_games_panel(self)
        games_panel.set_size_request(220, -1)
        games_panel.add_css_class("games-flyout-panel")
        self.games_list.connect("row-activated", lambda lb, row: self._close_games_flyout())

        self._flyout_backdrop = Gtk.Button()
        self._flyout_backdrop.add_css_class("flat")
        self._flyout_backdrop.set_hexpand(True)
        self._flyout_backdrop.set_vexpand(True)
        self._flyout_backdrop.set_visible(False)
        self._flyout_backdrop.connect("clicked", lambda _: self._close_games_flyout())
        content_overlay.add_overlay(self._flyout_backdrop)

        self._flyout_revealer = Gtk.Revealer()
        self._flyout_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self._flyout_revealer.set_transition_duration(200)
        self._flyout_revealer.set_halign(Gtk.Align.START)
        self._flyout_revealer.set_valign(Gtk.Align.FILL)
        self._flyout_revealer.set_child(games_panel)
        self._flyout_revealer.set_reveal_child(False)
        content_overlay.add_overlay(self._flyout_revealer)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_overlay.set_child(content)

        # Content stack: game view / settings / help
        self._content_stack = Gtk.Stack()
        self._content_stack.set_vexpand(True)
        self._content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._content_stack.set_transition_duration(120)
        content.append(self._content_stack)

        # ── Game view (ViewStack + top switcher) ──────────────────────────────
        game_view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._view_stack = Adw.ViewStack()
        self._view_stack.set_vexpand(True)
        self._view_stack.add_titled(
            self._build_profiles_tab(), "profiles", "Profiles"
        ).set_icon_name("system-users-symbolic")
        self._view_stack.add_titled(
            self._build_mod_engine_tab(), "mod-engine", "Mod Engine"
        ).set_icon_name("preferences-system-symbolic")
        self._view_stack.add_titled(
            self._build_mods_panel(), "mods", "Mods"
        ).set_icon_name("package-x-generic-symbolic")
        self.load_order_panel = build_load_order_panel(self)
        self._lo_page = self._view_stack.add_titled(self.load_order_panel, "load-order", "Load Order")
        self._lo_page.set_icon_name("view-list-symbolic")
        self._lo_page.set_visible(False)
        self._view_stack.connect("notify::visible-child", self._on_tab_switched)
        view_switcher = Adw.ViewSwitcher()
        view_switcher.set_stack(self._view_stack)
        view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        game_view.append(view_switcher)
        game_view.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        game_view.append(self._view_stack)
        self._content_stack.add_named(game_view, "game")

        # ── Settings page ─────────────────────────────────────────────────────
        self._content_stack.add_named(build_settings_panel(self), "settings")

        # ── Help page ─────────────────────────────────────────────────────────
        self._content_stack.add_named(build_help_panel(self), "help")

        # ── Status bar (always visible below content stack) ───────────────────
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
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_margin_top(12)
        header.set_margin_bottom(8)
        title = Gtk.Label(label="Profiles")
        title.add_css_class("heading")
        title.set_hexpand(True)
        title.set_xalign(0)
        header.append(title)
        self._profiles_active_label = Gtk.Label()
        self._profiles_active_label.add_css_class("dim-label")
        self._profiles_active_label.add_css_class("caption")
        self._profiles_active_label.set_valign(Gtk.Align.CENTER)
        header.append(self._profiles_active_label)
        panel.append(header)

        self._profiles_no_game = Gtk.Label(label="Select a game first")
        self._profiles_no_game.add_css_class("dim-label")
        self._profiles_no_game.set_vexpand(True)
        panel.append(self._profiles_no_game)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_visible(False)
        self._profiles_list = Gtk.ListBox()
        self._profiles_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._profiles_list.add_css_class("boxed-list")
        self._profiles_list.set_margin_start(12)
        self._profiles_list.set_margin_end(12)
        self._profiles_list.set_margin_bottom(4)
        scroll.set_child(self._profiles_list)
        panel.append(scroll)
        self._profiles_scroll = scroll

        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_bar.set_margin_start(12)
        btn_bar.set_margin_end(12)
        btn_bar.set_margin_top(8)
        btn_bar.set_margin_bottom(12)
        new_btn = Gtk.Button(label="+ New Profile")
        new_btn.set_hexpand(True)
        new_btn.connect("clicked", self._on_new_profile)
        btn_bar.append(new_btn)
        import_btn = Gtk.Button(label="Import Modpack…")
        import_btn.set_hexpand(True)
        import_btn.connect("clicked", self._on_import_modpack)
        btn_bar.append(import_btn)
        panel.append(btn_bar)

        # Kept for backward compat with collection.py handlers that reference it
        self._profiles_popover_box = Gtk.Box()
        self._profiles_popover_box.set_visible(False)
        panel.append(self._profiles_popover_box)

        return panel

    def _refresh_profiles_tab(self):
        if not self.engine or not self._game_slug:
            self._profiles_no_game.set_visible(True)
            self._profiles_scroll.set_visible(False)
            self._profiles_active_label.set_text("")
            return

        self._profiles_no_game.set_visible(False)
        self._profiles_scroll.set_visible(True)

        while child := self._profiles_list.get_first_child():
            self._profiles_list.remove(child)

        slug = self._game_slug
        all_profiles = _prof.load_all(slug)
        active_name = _prof.get_active(slug)
        self._profiles_active_label.set_text(f"Active: {active_name}" if active_name else "")

        mods_overview = None
        if self.engine and any(d.get("collection_mods") for d in all_profiles.values()):
            mods = self.engine.list_mods()
            mods_overview = (sum(1 for m in mods if m["active"]), len(mods))

        for name, data in all_profiles.items():
            self._profiles_list.append(self._make_profile_row(name, data, active_name, slug, mods_overview))

    def _make_profile_row(self, name, data, active_name, slug, mods_overview=None):
        row = Adw.ActionRow()
        row.set_title(name)
        if data.get("collection_mods") and mods_overview:
            n_active, total = mods_overview
            row.set_subtitle(f"{n_active} / {total} active")
        else:
            mod_count = len(data.get("active_mods", []))
            row.set_subtitle(f"{mod_count} mod{'s' if mod_count != 1 else ''}")

        if name == active_name:
            check = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
            check.add_css_class("success")
            row.add_prefix(check)

        load_btn = Gtk.Button(label="Load")
        load_btn.set_valign(Gtk.Align.CENTER)
        load_btn.add_css_class("flat" if name == active_name else "suggested-action")
        load_btn.connect("clicked", lambda _b, n=name: self._on_load_profile(n))
        row.add_suffix(load_btn)

        rename_btn = Gtk.Button(label="Rename")
        rename_btn.set_valign(Gtk.Align.CENTER)
        rename_btn.add_css_class("flat")
        rename_btn.connect("clicked", lambda _b, n=name: self._on_rename_profile(n))
        row.add_suffix(rename_btn)

        del_btn = Gtk.Button()
        del_btn.set_icon_name("user-trash-symbolic")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.add_css_class("flat")
        del_btn.connect("clicked", lambda _b, n=name: self._on_delete_profile(n))
        row.add_suffix(del_btn)

        return row

    def _on_new_profile(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="New Profile")
        entry = Gtk.Entry()
        entry.set_placeholder_text("Profile name")
        entry.set_activates_default(True)
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        entry.set_margin_bottom(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response != "save":
                return
            pname = entry.get_text().strip()
            if not pname:
                self._toast("Profile name cannot be empty")
                return
            active = [m["name"] for m in self.engine.list_mods() if m["active"]]
            order = self.engine.get_load_order() if self.engine.has_load_order else []
            _prof.save(self._game_slug, pname, active, order)
            self._toast(f"Saved profile: {pname}")
            self._refresh_profiles_tab()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_load_profile(self, name: str):
        from lsmm.gui.handlers.collection import apply_profile
        apply_profile(self, self._game_slug, name)
        self._refresh_profiles_tab()

    def _on_delete_profile(self, name: str):
        _prof.delete(self._game_slug, name)
        if _prof.get_active(self._game_slug) == name:
            _prof.set_active(self._game_slug, None)
        self._toast(f"Deleted profile: {name}")
        self._refresh_profiles_tab()

    def _on_rename_profile(self, old_name: str):
        from lsmm.gui.handlers.collection import _show_rename_dialog
        _show_rename_dialog(self, _TabRef(self._refresh_profiles_tab), self._game_slug, old_name)

    def _on_import_modpack(self, _btn):
        from lsmm.gui.handlers.collection import on_import_collection
        if not self.engine:
            self._toast("Select a game first")
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="Import Modpack from Nexus")
        entry = Gtk.Entry()
        entry.set_placeholder_text("https://www.nexusmods.com/…/collections/…")
        entry.set_activates_default(True)
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        entry.set_margin_bottom(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("import", "Import")
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("import")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response != "import":
                return
            url = entry.get_text().strip()
            if url:
                on_import_collection(self, url)

        dialog.connect("response", on_response)
        dialog.present()

    # ── Mod Engine tab ────────────────────────────────────────────────────────

    @staticmethod
    def _abbrev_path(path: Path) -> str:
        parts = path.parts
        return ("…/" + "/".join(parts[-3:])) if len(parts) > 3 else str(path)

    @staticmethod
    def _set_row(row: Adw.ActionRow, text: str, visible: bool = True) -> None:
        row.set_subtitle(text)
        row.set_visible(visible)

    @staticmethod
    def _set_se_row(row: Adw.ActionRow, val: Gtk.Label, text: str, visible: bool = True) -> None:
        val.set_text(text)
        row.set_visible(visible)

    @staticmethod
    def _set_version_label(lbl: Gtk.Label, text: str) -> None:
        import html
        if "up to date" in text:
            markup = f'<span foreground="#2ec27e">{html.escape(text)}</span>'
        elif "available" in text:
            markup = f'<span foreground="#e5a50a">{html.escape(text)}</span>'
        else:
            markup = html.escape(text)
        lbl.set_markup(markup)

    def _build_mod_engine_tab(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._mod_engine_placeholder = Adw.StatusPage()
        self._mod_engine_placeholder.set_icon_name("application-x-executable-symbolic")
        self._mod_engine_placeholder.set_title("No game selected")
        self._mod_engine_placeholder.set_description("Select a game from the Games menu")
        outer.append(self._mod_engine_placeholder)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_visible(False)

        self._mod_engine_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._mod_engine_content.set_margin_start(16)
        self._mod_engine_content.set_margin_end(16)
        self._mod_engine_content.set_margin_top(16)
        self._mod_engine_content.set_margin_bottom(16)
        scroll.set_child(self._mod_engine_content)

        # ── Panel header: "Mod Engine" fixed left + "Game · SE" right ───────────
        panel_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        panel_hdr.set_margin_bottom(4)
        _hdr_title = Gtk.Label(label="Mod Engine")
        _hdr_title.add_css_class("heading")
        _hdr_title.set_hexpand(True)
        _hdr_title.set_xalign(0)
        panel_hdr.append(_hdr_title)
        self._engine_sub_label = Gtk.Label()
        self._engine_sub_label.add_css_class("dim-label")
        self._engine_sub_label.add_css_class("caption")
        panel_hdr.append(self._engine_sub_label)
        self._mod_engine_content.append(panel_hdr)

        # ── Script Extender / Framework section ──────────────────────────────
        self._se_group = Adw.PreferencesGroup()
        self._mod_engine_content.append(self._se_group)

        def _make_se_info_row(title):
            row = Adw.ActionRow()
            row.set_title(title)
            lbl = Gtk.Label()
            lbl.set_halign(Gtk.Align.END)
            lbl.set_use_markup(True)
            lbl.add_css_class("dim-label")
            row.add_suffix(lbl)
            return row, lbl

        self._se_version_row, self._se_version_val = _make_se_info_row("Version")
        self._se_version_val.remove_css_class("dim-label")
        self._se_group.add(self._se_version_row)

        self._se_loader_row, self._se_loader_val = _make_se_info_row("Loader")
        self._se_group.add(self._se_loader_row)

        self._se_plugins_dir_row, self._se_plugins_val = _make_se_info_row("Plugins dir")
        self._se_group.add(self._se_plugins_dir_row)

        self._se_launch_row, self._se_launch_val = _make_se_info_row("Steam launch")
        self._se_group.add(self._se_launch_row)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.setup_btn = Gtk.Button()
        self.setup_btn.connect("clicked", self._on_setup_btn)
        btn_row.append(self.setup_btn)

        self._ensure_ini_btn = Gtk.Button(label="Ensure INI Settings")
        self._ensure_ini_btn.set_tooltip_text("Add bInvalidateOlderFiles=1 to the game's Custom INI")
        self._ensure_ini_btn.connect("clicked", self._on_ensure_ini)
        self._ensure_ini_btn.set_visible(False)
        btn_row.append(self._ensure_ini_btn)

        self._uninstall_se_btn = Gtk.Button(label="Uninstall SE")
        self._uninstall_se_btn.set_tooltip_text("Remove script extender files from game directory")
        self._uninstall_se_btn.add_css_class("destructive-action")
        self._uninstall_se_btn.connect("clicked", self._on_uninstall_se)
        self._uninstall_se_btn.set_visible(False)
        btn_row.append(self._uninstall_se_btn)

        verify_btn = Gtk.Button(label="Verify Paths")
        verify_btn.set_tooltip_text("Check that game and script extender paths exist")
        verify_btn.connect("clicked", self._on_verify_paths_btn)
        btn_row.append(verify_btn)
        self._mod_engine_content.append(btn_row)

        # ── Installation Paths section ────────────────────────────────────────
        self._paths_group = Adw.PreferencesGroup()
        self._paths_group.set_title("Installation Paths")
        edit_paths_btn = Gtk.Button(label="Edit")
        edit_paths_btn.add_css_class("flat")
        edit_paths_btn.set_valign(Gtk.Align.CENTER)
        edit_paths_btn.connect("clicked", self._on_edit_paths)
        self._paths_group.set_header_suffix(edit_paths_btn)
        self._mod_engine_content.append(self._paths_group)

        def _make_path_row(title):
            row = Adw.ActionRow()
            row.set_title(title)
            badge = Gtk.Label(label="auto")
            badge.add_css_class("dim-label")
            badge.add_css_class("caption")
            badge.set_margin_start(4)
            row.add_suffix(badge)
            return row

        self._path_game_root_row = _make_path_row("Game root")
        self._paths_group.add(self._path_game_root_row)

        self._path_mods_dir_row = _make_path_row("Mods dir")
        self._paths_group.add(self._path_mods_dir_row)

        self._path_data_dir_row = _make_path_row("Data dir")
        self._paths_group.add(self._path_data_dir_row)

        self._path_proton_row = _make_path_row("Proton prefix")
        self._paths_group.add(self._path_proton_row)

        self._path_plugins_txt_row = _make_path_row("Plugins.txt")
        self._paths_group.add(self._path_plugins_txt_row)

        outer.append(scroll)
        self._mod_engine_scroll = scroll
        return outer

    def _refresh_mod_engine_tab(self):
        if not self.engine:
            self._mod_engine_placeholder.set_visible(True)
            self._mod_engine_scroll.set_visible(False)
            return

        self._mod_engine_placeholder.set_visible(False)
        self._mod_engine_scroll.set_visible(True)
        self._ensure_ini_btn.set_visible(hasattr(self.engine, "ensure_ini"))
        _se_loader = getattr(getattr(self.engine, "paths", None), "se_loader", None)
        self._uninstall_se_btn.set_visible(bool(_se_loader and _se_loader.exists()))
        self._update_setup_btn()

        game_name = next((n for s, n in self.games if s == self._game_slug), self._game_slug or "")

        # ── SE / framework info rows ──────────────────────────────────────────
        paths = getattr(self.engine, "paths", None)
        se = getattr(paths, "script_extender", None) if paths else None
        game_root = getattr(paths, "game_root", None)
        if getattr(self.engine, "has_framework_setup", False):
            from lsmm.core.installer import load_manifest
            fw = getattr(self.engine, "framework_name", "BepInEx")
            fw_cfg = (self.engine.profile.get("smapi")
                      or self.engine.profile.get("bepinex")
                      or {})
            self._engine_sub_label.set_text(f"{game_name} · {fw}")
            self._se_group.set_title(fw)
            installed = self.engine.is_framework_installed()
            ver = load_manifest().get(fw, {}).get("nexus", {}).get("version") or ""
            self._se_version_row.set_title("Version")
            self._se_version_row.set_visible(True)
            github_repo = fw_cfg.get("github_repo")
            slug = self._game_slug or ""
            ver_prefix = f"v{ver}" if ver else "Installed"
            if not installed:
                self._set_version_label(self._se_version_val, "Not installed")
            elif github_repo:
                cached_ver = self._se_version_cache.get(slug)
                if cached_ver:
                    self._set_version_label(self._se_version_val, cached_ver)
                elif slug not in self._se_check_in_flight:
                    self._set_version_label(self._se_version_val, f"✓ {ver_prefix} — checking…")
                    self._se_check_in_flight.add(slug)
                    val_ref = self._se_version_val

                    def _fw_check(repo=github_repo, lbl=val_ref, s=slug, vp=ver_prefix):
                        latest = fetch_github_latest_tag(repo)
                        installed_raw = vp.lstrip("v") if vp != "Installed" else None
                        if latest:
                            if installed_raw and installed_raw == latest:
                                text = f"✓ {vp} — up to date"
                            elif installed_raw:
                                text = f"✓ {vp} — v{latest} available"
                            else:
                                text = f"✓ Installed — v{latest} available"
                        else:
                            text = f"✓ {vp}"
                        self._se_version_cache[s] = text
                        self._se_check_in_flight.discard(s)

                        def _update(t=text, lbl=lbl, s=s):
                            if self._game_slug == s:
                                self._set_version_label(lbl, t)
                            return False
                        GLib.idle_add(_update)
                    threading.Thread(target=_fw_check, daemon=True).start()
                else:
                    self._set_version_label(self._se_version_val, f"✓ {ver_prefix} — checking…")
            else:
                self._set_version_label(self._se_version_val, f"✓ {ver_prefix}" if installed else "Not installed")
            exe_name = fw_cfg.get("executable", fw)
            exe_path = (self.engine.game_root / exe_name) if exe_name else None
            self._se_loader_row.set_title("Executable")
            if exe_path:
                self._set_se_row(
                    self._se_loader_row, self._se_loader_val,
                    self._abbrev_path(exe_path) + ("  ✓" if exe_path.exists() else "  ✗ Not found"),
                )
            else:
                self._set_se_row(self._se_loader_row, self._se_loader_val, "", False)
            launch_name = fw_cfg.get("launch_script")
            launch_path = (self.engine.game_root / launch_name) if launch_name else None
            self._se_launch_row.set_title("Launch script")
            if launch_path and launch_path != exe_path:
                self._set_se_row(
                    self._se_launch_row, self._se_launch_val,
                    self._abbrev_path(launch_path) + ("  ✓" if launch_path.exists() else "  ✗ Not found"),
                )
            else:
                self._set_se_row(self._se_launch_row, self._se_launch_val, "", False)
            self._set_se_row(self._se_plugins_dir_row, self._se_plugins_val, "", False)
        elif se:
            se_name = se.get("name", "Script Extender")
            self._engine_sub_label.set_text(f"{game_name} · {se_name}")
            self._se_group.set_title(se_name)
            self._se_version_row.set_title("Version")
            self._se_loader_row.set_title("Loader")
            self._se_launch_row.set_title("Steam launch")
            se_loader = getattr(paths, "se_loader", None)
            se_installed = bool(se_loader and se_loader.exists())
            slug = self._game_slug or ""
            installed_ver = getattr(self.engine, "get_se_installed_version", lambda: None)()
            ver_prefix = f"v{installed_ver}" if installed_ver else "Installed"
            cached_ver = self._se_version_cache.get(slug)
            if not se_installed:
                self._se_version_row.set_visible(True)
                self._set_version_label(self._se_version_val, "✗ Not installed")
            elif cached_ver:
                self._se_version_row.set_visible(True)
                self._set_version_label(self._se_version_val, cached_ver)
            elif slug not in self._se_check_in_flight:
                self._se_version_row.set_visible(True)
                self._set_version_label(self._se_version_val, f"✓ {ver_prefix} — checking…")
                self._se_check_in_flight.add(slug)
                engine_ref = self.engine
                val_ref = self._se_version_val

                def _check(eng=engine_ref, lbl=val_ref, s=slug, vp=ver_prefix):
                    info = getattr(eng, "get_se_latest_info", lambda: None)()
                    if info:
                        latest = info[0].lstrip("v")
                        installed_raw = vp.lstrip("v") if vp != "Installed" else None
                        if installed_raw and installed_raw == latest:
                            text = f"✓ {vp} — up to date"
                        elif installed_raw:
                            text = f"✓ {vp} — v{latest} available"
                        else:
                            text = f"✓ Installed — v{latest} available"
                    else:
                        text = f"✓ {vp}"
                    self._se_version_cache[s] = text
                    self._se_check_in_flight.discard(s)

                    def _update(t=text, lbl=lbl, s=s):
                        if self._game_slug == s:
                            self._set_version_label(lbl, t)
                        return False
                    GLib.idle_add(_update)
                threading.Thread(target=_check, daemon=True).start()
            self._set_se_row(self._se_loader_row, self._se_loader_val,
                             self._abbrev_path(se_loader) if se_loader else "", bool(se_loader))
            se_plugins = getattr(paths, "se_plugins_dir", None)
            self._set_se_row(
                self._se_plugins_dir_row, self._se_plugins_val,
                self._abbrev_path(se_plugins) if se_plugins else "",
                bool(se_plugins),
            )
            launch_sh = (game_root / "se_launch.sh") if game_root else None
            launch_ok = bool(launch_sh and launch_sh.exists())
            self._set_se_row(
                self._se_launch_row, self._se_launch_val,
                "wrapper active ✓" if launch_ok else "not set up — run Setup below",
            )
        else:
            self._engine_sub_label.set_text(f"{game_name} · Folder mods")
            self._se_group.set_title("No Script Extender")
            self._set_se_row(self._se_version_row, self._se_version_val, "Folder-based mod loading")
            self._set_se_row(self._se_loader_row, self._se_loader_val, "", False)
            self._set_se_row(self._se_plugins_dir_row, self._se_plugins_val, "", False)
            self._set_se_row(self._se_launch_row, self._se_launch_val, "", False)

        # ── Installation paths rows ───────────────────────────────────────────
        if paths:
            data_dir = getattr(paths, "data_dir", None)
            proton = getattr(paths, "proton_prefix", None)
            plugins_txt = None
            try:
                plugins_txt = paths.plugins_txt
            except Exception:
                pass

            if game_root:
                exists = game_root.exists()
                self._path_game_root_row.set_subtitle(
                    self._abbrev_path(game_root) + ("  ✓" if exists else "  ✗ Not found")
                )
            self._path_game_root_row.set_visible(bool(game_root))
            mods_dir = getattr(paths, "mods_dir", None) or getattr(self.engine, "mods_dir", None)
            if mods_dir:
                exists = mods_dir.exists()
                self._path_mods_dir_row.set_subtitle(
                    self._abbrev_path(mods_dir)
                    + ("  ✓" if exists else "  — created on first install")
                )
            self._path_mods_dir_row.set_visible(bool(mods_dir))
            if data_dir:
                exists = data_dir.exists()
                self._path_data_dir_row.set_subtitle(
                    self._abbrev_path(data_dir) + ("  ✓" if exists else "  ✗ Not found")
                )
            self._path_data_dir_row.set_visible(bool(data_dir))
            if proton:
                exists = proton.exists()
                self._path_proton_row.set_subtitle(
                    self._abbrev_path(proton) + ("  ✓" if exists else "  — launch game once to create")
                )
            self._path_proton_row.set_visible(bool(proton))
            if plugins_txt:
                self._path_plugins_txt_row.set_subtitle(self._abbrev_path(plugins_txt))
                self._path_plugins_txt_row.set_visible(True)
            else:
                self._path_plugins_txt_row.set_visible(False)
            self._paths_group.set_visible(True)
        else:
            self._paths_group.set_visible(False)

    def _on_ensure_ini(self, _btn):
        if not self.engine or not hasattr(self.engine, "ensure_ini"):
            return
        try:
            self.engine.ensure_ini()
            self._toast("✓ INI settings applied")
        except Exception as e:
            self._toast(f"INI update failed: {e}")

    def _on_uninstall_se(self, _btn):
        if not self.engine or not hasattr(self.engine, "uninstall_script_extender"):
            return
        try:
            self.engine.uninstall_script_extender()
            self._se_version_cache.pop(self._game_slug or "", None)
            self._refresh_mod_engine_tab()
            self._toast("✓ Script extender removed")
        except Exception as e:
            self._toast(f"Uninstall failed: {e}")

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

    def _on_edit_paths(self, _btn):
        if not self.engine:
            return
        app_id = str(self.engine.profile.get("steam_app_id", ""))
        paths = getattr(self.engine, "paths", None)
        if not paths:
            return

        overrides = get_path_overrides(app_id)

        dialog = Adw.PreferencesDialog()
        dialog.set_title("Edit Installation Paths")

        dlg_page = Adw.PreferencesPage()
        dlg_page.set_title("Paths")
        dlg_page.set_icon_name("folder-symbolic")
        dialog.add(dlg_page)

        paths_grp = Adw.PreferencesGroup()
        paths_grp.set_title("Override Paths")
        paths_grp.set_description("Leave blank to use the auto-detected path")
        dlg_page.add(paths_grp)

        entries: dict[str, Adw.EntryRow] = {}

        def _add_entry(title, key, auto_val):
            row = Adw.EntryRow()
            row.set_title(title)
            row.set_text(overrides.get(key) or "")
            if auto_val:
                row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
            paths_grp.add(row)
            entries[key] = row

        _add_entry("Game root", "game_root", getattr(paths, "game_root", None))
        data_dir = getattr(paths, "data_dir", None)
        if data_dir is not None:
            _add_entry("Data dir", "data_dir", data_dir)
        proton = getattr(paths, "proton_prefix", None)
        if proton is not None:
            _add_entry("Proton prefix", "proton_prefix", proton)
        se = getattr(paths, "script_extender", None)
        if se:
            _add_entry("SE Loader", "se_loader", getattr(paths, "se_loader", None))
            _add_entry("SE Plugins dir", "se_plugins_dir", getattr(paths, "se_plugins_dir", None))

        action_grp = Adw.PreferencesGroup()
        dlg_page.add(action_grp)

        reset_row = Adw.ActionRow()
        reset_row.set_title("Reset to auto-detected")
        reset_row.set_activatable(True)
        reset_row.add_suffix(Gtk.Image.new_from_icon_name("edit-clear-symbolic"))

        def _on_reset(_row, *_):
            for entry in entries.values():
                entry.set_text("")

        reset_row.connect("activated", _on_reset)
        action_grp.add(reset_row)

        save_row = Adw.ActionRow()
        save_row.set_title("Save overrides")
        save_row.set_activatable(True)
        save_row.add_suffix(Gtk.Image.new_from_icon_name("document-save-symbolic"))

        def _on_save(_row, *_):
            new_overrides = {k: v.get_text().strip() for k, v in entries.items() if v.get_text().strip()}
            save_path_overrides(app_id, new_overrides)
            try:
                self.engine = _load_engine(self._game_slug)
            except Exception:
                pass
            self._refresh_mod_engine_tab()
            self._refresh_mods()
            self._update_action_sensitivity()
            self._update_setup_btn()
            GLib.idle_add(self._refresh_profiles_tab)
            dialog.close()
            self._toast("Path overrides saved")

        save_row.connect("activated", _on_save)
        action_grp.add(save_row)

        dialog.present(self)

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
        self._content_stack.set_visible_child_name("game")
        self._update_load_order_panel()
        self._refresh_mods()
        self._refresh_load_order()
        self._update_action_sensitivity()
        self.launch_btn.set_sensitive(bool(self.engine.profile.get("steam_app_id")))
        self._refresh_mod_engine_tab()
        GLib.idle_add(self._refresh_profiles_tab)
        self._fetch_tracked_mods(slug)

        paths = getattr(self.engine, "paths", None)
        if paths and hasattr(paths, "proton_prefix") and not paths.proton_prefix.exists():
            self._toast(f"{name}: launch the game once via Steam to create the Proton prefix")
        if paths and getattr(paths, "on_microsd", False):
            self._toast(f"{name}: game is on microSD — expect slower load times")

    # ── Steam path setup ──────────────────────────────────────────────────────

    def _toggle_games_flyout(self):
        if self._flyout_revealer.get_reveal_child():
            self._close_games_flyout()
        else:
            self._open_games_flyout()

    def _open_games_flyout(self):
        self._flyout_revealer.set_reveal_child(True)
        self._flyout_backdrop.set_visible(True)
        GLib.idle_add(self._games_search.grab_focus)

    def _close_games_flyout(self):
        self._flyout_revealer.set_reveal_child(False)
        self._flyout_backdrop.set_visible(False)

    def _init_steam_path(self):
        self._refresh_games()
        GLib.idle_add(self._open_games_flyout)
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

        self._tracked_group = Adw.PreferencesGroup()
        self._tracked_group.set_title("Tracked on Nexus")
        self._tracked_group.set_margin_start(12)
        self._tracked_group.set_margin_end(12)
        self._tracked_group.set_margin_top(8)
        self._tracked_group.set_margin_bottom(4)
        self._tracked_group.set_visible(False)
        panel.append(self._tracked_group)

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

    def _on_tab_switched(self, stack, _param):
        if not self.engine:
            return
        name = stack.get_visible_child_name()
        if name == "profiles":
            self._refresh_profiles_tab()
        elif name == "mod-engine":
            self._refresh_mod_engine_tab()
        elif name == "mods":
            self._refresh_mods()
        elif name == "load-order":
            self._refresh_load_order()

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

    def _fetch_tracked_mods(self, slug: str) -> None:
        api_key = get_nexus_api_key()
        if not api_key:
            return
        if slug in self._tracked_cache:
            self._populate_tracked_group(slug)
            return
        if slug in self._tracked_fetch_in_flight:
            return
        self._tracked_fetch_in_flight.add(slug)

        def _bg(s=slug, key=api_key):
            from lsmm.core.nexus import get_tracked_mods
            try:
                mods = get_tracked_mods(key)
            except Exception:
                mods = []
            self._tracked_cache[s] = mods
            self._tracked_fetch_in_flight.discard(s)
            GLib.idle_add(lambda: self._populate_tracked_group(s) or False)

        threading.Thread(target=_bg, daemon=True).start()

    def _populate_tracked_group(self, slug: str) -> None:
        if self._game_slug != slug:
            return

        while child := self._tracked_group.get_first_child():
            self._tracked_group.remove(child)

        tracked = self._tracked_cache.get(slug, [])
        if not tracked:
            self._tracked_group.set_visible(False)
            return

        profile = self.engine.profile if self.engine else {}
        nexus_domain = profile.get("nexus_domain", "")
        installed_ids = self._get_installed_nexus_mod_ids(slug)

        uninstalled = [
            m for m in tracked
            if m.get("domain_name", "").lower() == nexus_domain.lower()
            and int(m.get("mod_id", 0)) not in installed_ids
        ]

        if not uninstalled:
            self._tracked_group.set_visible(False)
            return

        self._tracked_group.set_visible(True)
        for mod in uninstalled:
            mod_id = mod.get("mod_id")
            mod_name = mod.get("name") or f"Mod #{mod_id}"
            row = Adw.ActionRow()
            row.set_title(mod_name)
            nexus_url = f"https://www.nexusmods.com/{nexus_domain}/mods/{mod_id}"
            open_btn = Gtk.Button(label="Open")
            open_btn.set_valign(Gtk.Align.CENTER)
            open_btn.add_css_class("flat")
            open_btn.connect("clicked", lambda _b, url=nexus_url: self._open_nexus_page(url))
            row.add_suffix(open_btn)
            self._tracked_group.add(row)

    def _open_nexus_page(self, url: str) -> None:
        import subprocess
        try:
            subprocess.Popen(["xdg-open", url])
        except Exception as e:
            self._toast(f"Could not open browser: {e}")

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
        if not get_check_updates_on_launch():
            return
        result = check_for_update()
        if result:
            tag, url = result
            if not is_update_snoozed(tag):
                GLib.idle_add(show_update_snooze_dialog, self, tag, url)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _toast(self, message: str):
        toast = Adw.Toast(title=GLib.markup_escape_text(message))
        self.toast_overlay.add_toast(toast)
