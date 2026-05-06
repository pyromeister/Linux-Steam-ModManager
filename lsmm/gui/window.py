"""ModManagerWindow — main application window."""

import re
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk, Gio

from lsmm.core.updater import check_for_update
from lsmm.core.config import (
    get_steam_root, get_steam_candidates,
    get_nexus_api_key,
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
from lsmm.gui.dialogs.api_key import show_api_key_dialog, show_nxm_api_key_hint
from lsmm.gui.dialogs.steam_path import show_steam_path_dialog
from lsmm.gui.dialogs.first_run import show_first_run_wizard
from lsmm.gui.dialogs.help import show_help_dialog


def _list_store_from_filter(f: Gtk.FileFilter) -> Gio.ListStore:
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    return store


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
        GLib.idle_add(self._init_steam_path)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root)

        self.update_banner = Adw.Banner()
        self.update_banner.set_button_label("Release Notes")
        self.update_banner.connect("button-clicked", self._on_update_banner_clicked)
        root.append(self.update_banner)

        header = Adw.HeaderBar()
        root.append(header)

        check_btn = Gtk.Button(label="Check")
        check_btn.connect("clicked", self._on_check)
        header.pack_end(check_btn)

        self.setup_btn = Gtk.Button(label="Setup SE")
        self.setup_btn.connect("clicked", self._on_setup_btn)
        header.pack_end(self.setup_btn)

        self.launch_btn = Gtk.Button(label="▶ Launch")
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.set_tooltip_text("Launch game via Steam")
        self.launch_btn.set_sensitive(False)
        self.launch_btn.connect("clicked", self._on_launch_game)
        header.pack_end(self.launch_btn)

        help_btn = Gtk.Button()
        help_btn.set_icon_name("help-about-symbolic")
        help_btn.set_tooltip_text("Help")
        help_btn.connect("clicked", lambda _: show_help_dialog(self))
        header.pack_start(help_btn)

        self._sidebar_btn = Gtk.ToggleButton()
        self._sidebar_btn.set_icon_name("sidebar-show-symbolic")
        self._sidebar_btn.set_tooltip_text("Toggle game list")
        self._sidebar_btn.set_active(True)
        header.pack_start(self._sidebar_btn)

        self._profiles_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._profiles_popover_box.set_margin_start(12)
        self._profiles_popover_box.set_margin_end(12)
        self._profiles_popover_box.set_margin_top(10)
        self._profiles_popover_box.set_margin_bottom(10)
        self._profiles_popover_box.set_size_request(280, -1)

        profiles_popover = Gtk.Popover()
        profiles_popover.set_autohide(True)
        profiles_popover.set_child(self._profiles_popover_box)
        profiles_popover.connect("show", lambda p: rebuild_profiles_popover(self, p))

        profiles_menu_btn = Gtk.MenuButton(label="Profiles/Modpacks")
        profiles_menu_btn.set_tooltip_text("Save and load mod profiles")
        profiles_menu_btn.set_popover(profiles_popover)
        header.pack_start(profiles_menu_btn)

        self.mods_content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.mods_content_box.append(self._build_mods_panel())

        split_view = Adw.OverlaySplitView()
        split_view.set_vexpand(True)
        split_view.set_sidebar(build_games_panel(self))
        split_view.set_content(self.mods_content_box)
        split_view.set_sidebar_position(Gtk.PackType.START)
        root.append(split_view)

        self._sidebar_btn.bind_property(
            "active", split_view, "show-sidebar",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )

        self.load_order_panel = build_load_order_panel(self)

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

        root.append(status_bar)
        self._pulse_source_id: int | None = None

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
        self._update_setup_btn()
        self.launch_btn.set_sensitive(bool(self.engine.profile.get("steam_app_id")))

    # ── Steam path setup ──────────────────────────────────────────────────────

    def _init_steam_path(self):
        self._refresh_games()
        if get_steam_root() is None and get_nexus_api_key() is None:
            # Truly first run — walk the user through full setup.
            show_first_run_wizard(self)
        elif get_steam_root() is None:
            # Returning user with API key already set, but Steam root missing.
            show_steam_path_dialog(self, get_steam_candidates())
        if self._pending_nxm:
            nxm_url = self._pending_nxm
            self._pending_nxm = None
            GLib.idle_add(self._handle_startup_nxm, nxm_url)

    def _update_load_order_panel(self):
        if self.engine.has_load_order:
            if self.load_order_panel.get_parent() is None:
                self.mods_content_box.append(self.load_order_panel)
        else:
            if self.load_order_panel.get_parent() is not None:
                self.mods_content_box.remove(self.load_order_panel)

    # ── Mods panel ────────────────────────────────────────────────────────────

    def _build_mods_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_size_request(680, -1)

        header_label = Gtk.Label(label="Installed Mods")
        header_label.add_css_class("heading")
        header_label.set_margin_top(12)
        header_label.set_margin_bottom(8)
        panel.append(header_label)

        self.mods_search = Gtk.SearchEntry()
        self.mods_search.set_placeholder_text("Search mods…")
        self.mods_search.set_margin_start(12)
        self.mods_search.set_margin_end(12)
        self.mods_search.set_margin_bottom(8)
        self.mods_search.connect("search-changed", self._on_mods_search_changed)
        panel.append(self.mods_search)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panel.append(scroll)

        self.mods_list = Gtk.ListBox()
        self.mods_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.mods_list.add_css_class("boxed-list")
        self.mods_list.set_margin_start(12)
        self.mods_list.set_margin_end(12)
        self.mods_list.set_filter_func(self._mods_filter_func)
        scroll.set_child(self.mods_list)

        self.empty_label = Gtk.Label(label="No mods installed")
        self.empty_label.add_css_class("dim-label")
        self.empty_label.set_margin_top(48)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_start(12)
        btn_box.set_margin_end(12)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(12)

        install_btn = Gtk.Button(label="+ Install")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", self._on_install)
        install_btn.set_hexpand(True)
        btn_box.append(install_btn)

        self.uninstall_btn = Gtk.Button(label="- Uninstall")
        self.uninstall_btn.add_css_class("destructive-action")
        self.uninstall_btn.connect("clicked", self._on_uninstall)
        self.uninstall_btn.set_hexpand(True)
        btn_box.append(self.uninstall_btn)

        nxm_btn = Gtk.Button(label="NXM URL")
        nxm_btn.set_tooltip_text("Import mod via Nexus nxm:// link")
        nxm_btn.connect("clicked", self._on_nxm_import)
        nxm_btn.set_hexpand(True)
        btn_box.append(nxm_btn)

        update_btn = Gtk.Button(label="Check Updates")
        update_btn.set_tooltip_text("Check Nexus Mods for updates to installed mods")
        update_btn.connect("clicked", self._on_check_updates)
        update_btn.set_hexpand(True)
        btn_box.append(update_btn)

        panel.append(btn_box)
        return panel

    # ── Mod list ──────────────────────────────────────────────────────────────

    def _refresh_mods(self):
        while child := self.mods_list.get_first_child():
            self.mods_list.remove(child)

        try:
            mods = self.engine.list_mods()
        except Exception as e:
            self._toast(f"Could not load mod list: {e}")
            self.mods_list.append(self.empty_label)
            return

        if not mods:
            self.mods_list.append(self.empty_label)
            return

        for mod in sorted(mods, key=lambda m: m["name"].lower()):
            row = ModRow(mod, self._on_toggle_mod)
            self.mods_list.append(row)

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
        threading.Thread(target=run, daemon=True).start()

    # ── Install ───────────────────────────────────────────────────────────────

    def _on_install(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
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
            self._toast("Select a game first")
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
            self._toast("Select a game first")
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
            self._toast("Select a game first")
            return
        api_key = get_nexus_api_key()
        if not api_key:
            show_api_key_dialog(self)
            return
        do_check_updates(self, api_key)

    # ── Profiles ──────────────────────────────────────────────────────────────

    def _get_installed_nexus_mod_ids(self, game_slug: str) -> set:
        """Return set of nexus mod_ids installed for this game (from manifest)."""
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
        return ids

    # ── Header actions ────────────────────────────────────────────────────────

    def _on_check(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return
        if hasattr(self.engine, "verify"):
            warnings = self.engine.verify()
        elif hasattr(self.engine, "paths"):
            warnings = self.engine.paths.verify()
        else:
            self._toast("Check not supported for this engine")
            return
        if warnings:
            self._toast(f"⚠ {warnings[0]}" + (f" (+{len(warnings)-1} more)" if len(warnings) > 1 else ""))
        else:
            self._toast("✓ All paths verified")

    def _update_setup_btn(self):
        if not self.engine:
            self.setup_btn.set_label("Setup SE")
            self.setup_btn.set_sensitive(False)
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
            self.setup_btn.set_label("Setup SE")
            self.setup_btn.set_tooltip_text("Create the script extender launch wrapper")
        else:
            self.setup_btn.set_label("Setup SE")
            self.setup_btn.set_sensitive(False)

    def _on_setup_btn(self, _btn):
        setup_handler.handle_setup_btn(self)

    # ── Update check ──────────────────────────────────────────────────────────

    def _check_for_update(self):
        result = check_for_update()
        if result:
            tag, url = result
            self._update_release_url = url
            GLib.idle_add(self._show_update_banner, tag)

    def _show_update_banner(self, tag: str):
        self.update_banner.set_title(f"Update available: {tag}")
        self.update_banner.set_revealed(True)

    def _on_update_banner_clicked(self, _banner):
        url = getattr(self, "_update_release_url", None)
        if url:
            Gtk.UriLauncher.new(url).launch(self, None, None, None)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _toast(self, message: str):
        toast = Adw.Toast(title=GLib.markup_escape_text(message))
        self.toast_overlay.add_toast(toast)
