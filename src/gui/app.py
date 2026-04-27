"""
GTK4 + libadwaita GUI for Linux Steam ModManager.
Adaptive layout: load order panel only shown when engine.has_load_order is True.
Install operations run in background thread to keep UI responsive.
"""

import json
import sys
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Gio, Pango

# Bootstrap paths
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "engines"))

from config import (
    load_profile, GAMES_DIR, ARCHIVES_DIR,
    get_steam_root, get_steam_candidates, save_steam_root,
    get_nexus_api_key, save_nexus_api_key,
)

sys.path.insert(0, str(ROOT / "engines"))
from installer import ConflictError


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_engine(game: str):
    profile = load_profile(game)
    profile["slug"] = game
    engine_name = profile["engine"]
    if engine_name == "bethesda":
        from bethesda import BethesdaEngine
        return BethesdaEngine(profile)
    if engine_name == "bepinex":
        from bepinex import BepInExEngine
        return BepInExEngine(profile)
    if engine_name == "rimworld":
        from rimworld import RimWorldEngine
        return RimWorldEngine(profile)
    if engine_name == "modfolder":
        from modfolder import ModFolderEngine
        return ModFolderEngine(profile)
    raise ValueError(f"Engine '{engine_name}' not yet implemented")


def find_game_by_nexus_domain(domain: str) -> str | None:
    """Return the game slug whose nexus_domain matches *domain*, or None."""
    for p in GAMES_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("nexus_domain", "").lower() == domain.lower():
                return p.stem
        except Exception:
            continue
    return None


def available_games() -> list[tuple[str, str]]:
    """Returns [(slug, display_name), ...]"""
    result = []
    for p in sorted(GAMES_DIR.glob("*.json")):
        data = json.loads(p.read_text())
        result.append((p.stem, data["name"]))
    return result


# ── Mod row widget ────────────────────────────────────────────────────────────

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
        if kind in ("se_plugin", "framework"):
            if kind == "framework":
                sub_text = "Framework (not tracked)" if mod.get("untracked") else "Framework"
            else:
                sub_text = "SE Plugin"
            sub = Gtk.Label(label=sub_text)
            sub.set_xalign(0)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            label_box.append(sub)


# ── Load order row widget ─────────────────────────────────────────────────────

class PluginRow(Gtk.ListBoxRow):
    def __init__(self, name: str, index: int, on_move=None):
        super().__init__()
        self.plugin_name = name
        self._on_move = on_move

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(5)
        box.set_margin_bottom(5)
        self.set_child(box)

        self._num_label = Gtk.Label(label=str(index + 1))
        self._num_label.add_css_class("dim-label")
        self._num_label.add_css_class("caption")
        self._num_label.set_valign(Gtk.Align.CENTER)
        self._num_label.set_size_request(24, -1)
        self._num_label.set_xalign(1)
        box.append(self._num_label)

        label = Gtk.Label(label=name)
        label.set_hexpand(True)
        label.set_xalign(0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_valign(Gtk.Align.CENTER)
        box.append(label)

        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.add_css_class("drag-handle")
        handle.set_valign(Gtk.Align.CENTER)
        box.append(handle)

        if on_move:
            drag_source = Gtk.DragSource()
            drag_source.set_actions(Gdk.DragAction.MOVE)
            drag_source.connect("prepare", self._drag_prepare)
            drag_source.connect("drag-begin", self._drag_begin)
            box.add_controller(drag_source)

            drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
            drop_target.connect("drop", self._drag_drop)
            box.add_controller(drop_target)

    def renumber(self, index: int) -> None:
        self._num_label.set_text(str(index + 1))

    def _drag_prepare(self, source, x, y):
        value = GObject.Value()
        value.init(GObject.TYPE_STRING)
        value.set_string(self.plugin_name)
        return Gdk.ContentProvider.new_for_value(value)

    def _drag_begin(self, source, drag):
        paintable = Gtk.WidgetPaintable.new(self)
        source.set_icon(paintable, 0, 0)

    def _drag_drop(self, target, value, x, y):
        if value != self.plugin_name and self._on_move:
            self._on_move(value, self.plugin_name)
        return True


# ── Main window ───────────────────────────────────────────────────────────────

class ModManagerWindow(Adw.ApplicationWindow):
    def __init__(self, app, pending_nxm: str | None = None):
        super().__init__(application=app)
        self.set_title("Linux Steam ModManager")
        self.set_default_size(1280, 800)

        self.engine = None
        self.games = available_games()
        self._installing = False
        self._game_slug = None
        self._pending_nxm: str | None = pending_nxm

        self._build_ui()
        self._update_setup_btn()
        GLib.idle_add(self._init_steam_path)

    def _build_ui(self):
        # Toast overlay wraps everything
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Root box
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root)

        # Header bar
        header = Adw.HeaderBar()
        root.append(header)

        # Header buttons — right side
        check_btn = Gtk.Button(label="Check")
        check_btn.connect("clicked", self._on_check)
        header.pack_end(check_btn)

        self.setup_btn = Gtk.Button(label="Setup SE")
        self.setup_btn.connect("clicked", self._on_setup_btn)
        header.pack_end(self.setup_btn)

        # Header buttons — left side
        help_btn = Gtk.Button()
        help_btn.set_icon_name("help-about-symbolic")
        help_btn.set_tooltip_text("Help")
        help_btn.connect("clicked", self._on_help)
        header.pack_start(help_btn)

        self._profiles_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._profiles_popover_box.set_margin_start(12)
        self._profiles_popover_box.set_margin_end(12)
        self._profiles_popover_box.set_margin_top(10)
        self._profiles_popover_box.set_margin_bottom(10)
        self._profiles_popover_box.set_size_request(280, -1)

        profiles_popover = Gtk.Popover()
        profiles_popover.set_autohide(True)
        profiles_popover.set_child(self._profiles_popover_box)
        profiles_popover.connect("show", self._rebuild_profiles_popover)

        profiles_menu_btn = Gtk.MenuButton(label="Profiles/Modpacks")
        profiles_menu_btn.set_tooltip_text("Save and load mod profiles")
        profiles_menu_btn.set_popover(profiles_popover)
        header.pack_start(profiles_menu_btn)

        # Content: three-column horizontal split
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.content_box.set_vexpand(True)
        root.append(self.content_box)

        # Column 1 — games
        self.content_box.append(self._build_games_panel())
        self.content_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Column 2 — installed mods
        self.content_box.append(self._build_mods_panel())

        # Column 3 — load order (added dynamically based on engine)
        self.load_order_panel = self._build_load_order_panel()

        # Status bar
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

    # ── Progress bar helpers (call from main thread only via GLib.idle_add) ───

    def _progress_start_pulse(self) -> None:
        """Show progress bar in indeterminate pulse mode."""
        self.progress_bar.set_visible(True)
        self.progress_bar.set_fraction(0.0)
        if self._pulse_source_id is None:
            self._pulse_source_id = GLib.timeout_add(80, self._on_pulse_tick)

    def _on_pulse_tick(self) -> bool:
        self.progress_bar.pulse()
        return True  # keep ticking

    def _progress_set(self, fraction: float) -> None:
        """Show progress bar at a specific fraction (0.0–1.0)."""
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None
        self.progress_bar.set_visible(True)
        self.progress_bar.set_fraction(max(0.0, min(1.0, fraction)))

    def _progress_done(self) -> None:
        """Hide progress bar and stop any pulse timer."""
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_visible(False)

    def _build_games_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_size_request(200, -1)

        header_label = Gtk.Label(label="Games")
        header_label.add_css_class("heading")
        header_label.set_margin_top(12)
        header_label.set_margin_bottom(8)
        panel.append(header_label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panel.append(scroll)

        self.games_list = Gtk.ListBox()
        self.games_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.games_list.add_css_class("boxed-list")
        self.games_list.set_margin_start(8)
        self.games_list.set_margin_end(8)
        self.games_list.connect("row-activated", self._on_game_row_activated)
        scroll.set_child(self.games_list)

        # Add / Remove buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_margin_start(8)
        btn_box.set_margin_end(8)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(10)

        add_btn = Gtk.Button(label="+ Add")
        add_btn.set_hexpand(True)
        add_btn.connect("clicked", self._on_add_game)
        btn_box.append(add_btn)

        self.remove_game_btn = Gtk.Button(label="- Remove")
        self.remove_game_btn.set_hexpand(True)
        self.remove_game_btn.add_css_class("destructive-action")
        self.remove_game_btn.connect("clicked", self._on_remove_game)
        self.remove_game_btn.set_sensitive(False)
        btn_box.append(self.remove_game_btn)

        panel.append(btn_box)
        return panel

    def _refresh_games(self):
        """Rebuild the games list box from games/*.json."""
        while child := self.games_list.get_first_child():
            self.games_list.remove(child)
        self.games = available_games()
        for slug, name in self.games:
            row = Gtk.ListBoxRow()
            row._slug = slug
            lbl = Gtk.Label(label=name)
            lbl.set_xalign(0)
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            lbl.set_margin_top(6)
            lbl.set_margin_bottom(6)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            row.set_child(lbl)
            self.games_list.append(row)
        # Re-select current game if still present
        if self._game_slug:
            for row in self._iter_game_rows():
                if row._slug == self._game_slug:
                    self.games_list.select_row(row)
                    self.remove_game_btn.set_sensitive(True)
                    break

    def _iter_game_rows(self):
        row = self.games_list.get_first_child()
        while row:
            if isinstance(row, Gtk.ListBoxRow):
                yield row
            row = row.get_next_sibling()

    def _on_game_row_activated(self, listbox, row):
        slug = row._slug
        self.remove_game_btn.set_sensitive(True)
        self._select_game(slug)

    def _on_add_game(self, _btn):
        """Import a game profile .json — opens directly in the games/ folder."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Select game profile (.json)")
        filters = Gtk.FileFilter()
        filters.set_name("JSON profiles (*.json)")
        filters.add_pattern("*.json")
        store = Gio_ListStore_from_filter(filters)
        dialog.set_filters(store)
        # Start the file chooser inside games/ so the user sees existing profiles
        games_dir_file = Gio.File.new_for_path(str(GAMES_DIR))
        dialog.set_initial_folder(games_dir_file)
        dialog.open(self, None, self._on_game_profile_selected)

    def _on_game_profile_selected(self, dialog, result):
        try:
            f = dialog.open_finish(result)
        except Exception:
            return
        if f is None:
            return
        src = Path(f.get_path())
        dst = GAMES_DIR / src.name
        if dst.exists():
            self._toast(f"Profile already exists: {src.name}")
            return
        try:
            import shutil
            shutil.copy2(src, dst)
            self._refresh_games()
            self._toast(f"Added game profile: {src.stem}")
        except Exception as e:
            self._toast(f"Failed to add profile: {e}")

    def _on_remove_game(self, _btn):
        row = self.games_list.get_selected_row()
        if row is None:
            return
        slug = row._slug
        _, name = next(((s, n) for s, n in self.games if s == slug), (slug, slug))
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f'Remove "{name}"?',
            body="This deletes the game profile file from games/. Installed mods are not affected.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove Profile")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda d, r: self._do_remove_game(slug) if r == "remove" else None)
        dialog.present()

    def _do_remove_game(self, slug: str):
        path = GAMES_DIR / f"{slug}.json"
        try:
            path.unlink()
        except Exception as e:
            self._toast(f"Failed to remove: {e}")
            return
        if self._game_slug == slug:
            self.engine = None
            self._game_slug = None
            self.set_title("Linux Steam ModManager")
            self._refresh_mods()
            self._refresh_load_order()
            self.remove_game_btn.set_sensitive(False)
        self._refresh_games()
        self._toast(f"Removed profile: {slug}")

    def _build_mods_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_size_request(680, -1)

        # Panel header
        header_label = Gtk.Label(label="Installed Mods")
        header_label.add_css_class("heading")
        header_label.set_margin_top(12)
        header_label.set_margin_bottom(8)
        panel.append(header_label)

        # Scrollable mod list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panel.append(scroll)

        self.mods_list = Gtk.ListBox()
        self.mods_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.mods_list.add_css_class("boxed-list")
        self.mods_list.set_margin_start(12)
        self.mods_list.set_margin_end(12)
        scroll.set_child(self.mods_list)

        # Empty state
        self.empty_label = Gtk.Label(label="No mods installed")
        self.empty_label.add_css_class("dim-label")
        self.empty_label.set_margin_top(48)

        # Action buttons
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

    def _build_load_order_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_size_request(300, -1)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        panel.append(sep)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.append(inner)

        header_label = Gtk.Label(label="Load Order")
        header_label.add_css_class("heading")
        header_label.set_margin_top(12)
        header_label.set_margin_bottom(8)
        inner.append(header_label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inner.append(scroll)

        self.plugins_list = Gtk.ListBox()
        self.plugins_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.plugins_list.add_css_class("boxed-list")
        self.plugins_list.set_margin_start(12)
        self.plugins_list.set_margin_end(12)
        scroll.set_child(self.plugins_list)

        save_btn = Gtk.Button(label="Save Order")
        save_btn.set_margin_start(12)
        save_btn.set_margin_end(12)
        save_btn.set_margin_top(8)
        save_btn.set_margin_bottom(12)
        save_btn.connect("clicked", self._on_save_order)
        inner.append(save_btn)

        return panel

    # ── Game selection ────────────────────────────────────────────────────────

    def _select_game(self, slug: str):
        name = next((n for s, n in self.games if s == slug), slug)
        try:
            self.engine = load_engine(slug)
        except Exception as e:
            self._toast(f"Failed to load engine: {e}")
            return

        self._game_slug = slug
        self.set_title(f"Linux Steam ModManager — {name}")
        self._update_load_order_panel()
        self._refresh_mods()
        self._refresh_load_order()
        self._update_setup_btn()

    # ── Steam path setup ──────────────────────────────────────────────────────

    def _init_steam_path(self):
        self._refresh_games()
        if get_steam_root() is None:
            self._show_steam_path_dialog(get_steam_candidates())
        if self._pending_nxm:
            nxm_url = self._pending_nxm
            self._pending_nxm = None
            GLib.idle_add(self._handle_startup_nxm, nxm_url)

    def _show_steam_path_dialog(self, candidates: list):
        self._steam_candidates = candidates  # stored for index-based response lookup

        if not candidates:
            body = (
                "Steam was not found automatically.\n"
                "Please select your Steam data folder manually.\n\n"
                "Typical location: <tt>~/.local/share/Steam</tt>"
            )
        else:
            lines = "\n".join(
                f"{i+1}. <tt>{p}</tt>  ({self._steam_path_label(p)})"
                for i, p in enumerate(candidates)
            )
            body = (
                f"Multiple Steam installations were detected:\n\n{lines}\n\n"
                "Select one below, or browse to a custom location."
            )

        dialog = Adw.MessageDialog(transient_for=self, heading="Steam Installation")
        dialog.set_body(body)
        dialog.set_body_use_markup(True)

        for i in range(len(candidates)):
            dialog.add_response(str(i), str(i + 1))

        dialog.add_response("browse", "Browse…")
        dialog.connect("response", self._on_steam_path_response)
        dialog.present()

    @staticmethod
    def _steam_path_label(path) -> str:
        s = str(path)
        if ".var/app/" in s:      # Flatpak path pattern
            return "Flatpak"
        if "/snap/" in s:         # Snap path pattern
            return "Snap"
        return "Native"

    def _apply_steam_path(self, chosen: Path):
        if (chosen / "steamapps").exists():
            save_steam_root(chosen)
            self._refresh_games()
        else:
            self._toast("That folder is not a valid Steam installation (no steamapps/ found)")
            self._show_steam_path_dialog(get_steam_candidates())

    def _on_steam_path_response(self, dialog, response_id: str):
        if response_id == "browse":
            folder_dialog = Gtk.FileDialog()
            folder_dialog.set_title("Select Steam data folder")
            folder_dialog.select_folder(self, None, self._on_steam_folder_selected)
            return

        self._apply_steam_path(self._steam_candidates[int(response_id)])

    def _on_steam_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except Exception:
            return
        if folder is not None:
            self._apply_steam_path(Path(folder.get_path()))

    def _on_help(self, _btn):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="How to use the Mod Manager",
            body=(
                "<b>Installed Mods panel (left)</b>\n"
                "Shows all mods tracked by the manager. "
                "Check/uncheck a mod to enable or disable it (toggles its plugin in the load order).\n\n"
                "<b>Load Order panel (right)</b>\n"
                "Lists all active plugins in the order the game loads them. "
                "Drag rows to reorder. Click <b>Save Order</b> to write the new order — "
                "you must save or your changes will be lost on close.\n\n"
                "<b>+ Install</b>\n"
                "Opens a file picker. Select one or more .zip / .7z / .rar archives. "
                "Each archive is extracted and its files are placed in the correct Data/ folder automatically.\n\n"
                "<b>Setup SE</b>\n"
                "Creates a launch script for the Script Extender (SFSE/SKSE/F4SE). "
                "After clicking, copy the displayed text into Steam → game Properties → Launch Options.\n\n"
                "<b>Check</b>\n"
                "Verifies that the game folder and Script Extender files exist at the expected paths.\n\n"
                "<b>SE Plugin</b> tag in mod list\n"
                "Mods shown with this tag are DLL plugins found in the SE plugins folder. "
                "They were not installed through this manager — remove them manually if needed.\n\n"
                "<b>NXM URL</b> (experimental)\n"
                'Click "NXM URL", paste an <tt>nxm://</tt> link from Nexus Mods. '
                "Requires a free Nexus API key (nexusmods.com → Account → API Keys).\n\n"
                '<a href="https://github.com/pyromaster/linux-sfse-modlauncher">'
                "GitHub Repository</a>"
            ),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("ok", "Got it")
        dialog.present()

    def _update_load_order_panel(self):
        if self.engine.has_load_order:
            if self.load_order_panel.get_parent() is None:
                self.content_box.append(self.load_order_panel)
        else:
            if self.load_order_panel.get_parent() is not None:
                self.content_box.remove(self.load_order_panel)

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

        for mod in mods:
            row = ModRow(mod, self._on_toggle_mod)
            self.mods_list.append(row)

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
        filter_list = Gio_ListStore_from_filter(filters)
        dialog.set_filters(filter_list)

        dialog.open_multiple(self, None, self._on_files_selected)

    def _on_files_selected(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except Exception:
            return

        paths = [Path(files.get_item(i).get_path()) for i in range(files.get_n_items())]
        if not paths:
            return

        self._install_batch(paths)

    def _install_batch(self, paths: list[Path]):
        if self._installing:
            self._toast("Installation already in progress")
            return

        self._installing = True

        def run():
            GLib.idle_add(self._progress_start_pulse)
            for i, path in enumerate(paths):
                GLib.idle_add(
                    self.status_label.set_text,
                    f"Installing {path.name} ({i+1}/{len(paths)})..."
                )
                try:
                    self.engine.install(path)
                except ConflictError as ce:
                    confirmed = self._ask_conflict(ce.conflicts, path.name)
                    if confirmed:
                        try:
                            self.engine.install(path, force=True)
                        except Exception as e:
                            GLib.idle_add(self._toast, f"Failed: {path.name} — {e}")
                except Exception as e:
                    GLib.idle_add(self._toast, f"Failed: {path.name} — {e}")

            self._installing = False
            GLib.idle_add(self._progress_done)
            GLib.idle_add(self.status_label.set_text, "Ready")
            GLib.idle_add(self._refresh_mods)
            GLib.idle_add(self._refresh_load_order)

        threading.Thread(target=run, daemon=True).start()

    def _ask_conflict(self, conflicts: list[tuple[str, str]], mod_name: str) -> bool:
        """
        Called from a background thread. Shows a conflict dialog on the main
        thread and blocks until the user responds. Returns True = install anyway.
        """
        event = threading.Event()
        result = [False]
        GLib.idle_add(self._show_conflict_dialog, conflicts, mod_name, event, result)
        event.wait()
        return result[0]

    def _show_conflict_dialog(
        self,
        conflicts: list[tuple[str, str]],
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
            transient_for=self,
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
        def run():
            self.engine.uninstall(mod_name)
            GLib.idle_add(self._refresh_mods)
            GLib.idle_add(self._refresh_load_order)
            GLib.idle_add(self._update_setup_btn)
            GLib.idle_add(self._toast, f"Uninstalled: {mod_name}")
        threading.Thread(target=run, daemon=True).start()

    # ── Load order ────────────────────────────────────────────────────────────

    def _refresh_load_order(self):
        if not self.engine or not self.engine.has_load_order:
            return

        while child := self.plugins_list.get_first_child():
            self.plugins_list.remove(child)

        for i, name in enumerate(self.engine.get_load_order()):
            self.plugins_list.append(PluginRow(name, i, self._move_plugin))

    def _on_save_order(self, _btn):
        order = []
        child = self.plugins_list.get_first_child()
        while child:
            if isinstance(child, PluginRow):
                order.append(child.plugin_name)
            child = child.get_next_sibling()
        self.engine.set_load_order(order)
        self._toast("Load order saved")

    def _move_plugin(self, dragged_name: str, target_name: str):
        """Reorder load order list: move dragged_name above target_name."""
        order = []
        child = self.plugins_list.get_first_child()
        while child:
            if isinstance(child, PluginRow):
                order.append(child.plugin_name)
            child = child.get_next_sibling()

        if dragged_name not in order or target_name not in order or dragged_name == target_name:
            return

        order.remove(dragged_name)
        order.insert(order.index(target_name), dragged_name)

        while child := self.plugins_list.get_first_child():
            self.plugins_list.remove(child)
        for i, name in enumerate(order):
            self.plugins_list.append(PluginRow(name, i, self._move_plugin))

    # ── NXM import ────────────────────────────────────────────────────────────

    def _handle_startup_nxm(self, url: str) -> bool:
        from nexus import parse_nxm
        parsed = parse_nxm(url)
        if not parsed:
            self._toast(f"Invalid NXM URL: {url[:60]}")
            return GLib.SOURCE_REMOVE

        slug = find_game_by_nexus_domain(parsed.get("game_domain", ""))
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
            self._show_nxm_api_key_hint()
            return GLib.SOURCE_REMOVE

        self._do_nxm_import(url, api_key)
        return GLib.SOURCE_REMOVE

    def handle_nxm_url(self, url: str) -> None:
        """Called by ModManagerApp when an NXM URL arrives in a running instance."""
        self.present()
        GLib.idle_add(self._handle_startup_nxm, url)

    def _show_nxm_api_key_hint(self) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Nexus API Key Required",
            body=(
                "A Nexus API key is required to use Mod Manager Download links.\n"
                "Get it at nexusmods.com → Account → API Keys.\n\n"
                "After saving, click Mod Manager Download in your browser again."
            ),
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("Your Nexus API key")
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save Key")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response == "save":
                key = entry.get_text().strip()
                if key:
                    save_nexus_api_key(key)

        dialog.connect("response", _on_response)
        dialog.present()

    def _on_nxm_import(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return

        api_key = get_nexus_api_key()
        if not api_key:
            self._show_api_key_dialog(then_open_nxm=True)
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
            lambda d, r: self._do_nxm_import(entry.get_text(), api_key) if r == "import" else None,
        )
        dialog.present()

    def _show_api_key_dialog(self, then_open_nxm=False):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Nexus API Key Required",
            body="Get your key at nexusmods.com → Account → API Keys:",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("Your Nexus API key")
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        entry.set_margin_bottom(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save Key")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def on_response(d, r):
            if r == "save":
                key = entry.get_text().strip()
                if key:
                    save_nexus_api_key(key)
                    if then_open_nxm:
                        self._on_nxm_import(None)

        dialog.connect("response", on_response)
        dialog.present()

    def _do_nxm_import(self, url: str, api_key: str):
        from nexus import parse_nxm, get_download_link, download_file

        nxm = parse_nxm(url.strip())
        if not nxm:
            self._toast("Invalid NXM URL — expected nxm://...")
            return

        def run():
            try:
                GLib.idle_add(self.status_label.set_text, "Getting download link from Nexus...")
                dl_url = get_download_link(nxm, api_key)

                filename = dl_url.split("/")[-1].split("?")[0]
                slug = self._game_slug or "unknown"
                dest = ARCHIVES_DIR / slug / filename

                GLib.idle_add(self.status_label.set_text, f"Downloading {filename}...")
                GLib.idle_add(self._progress_set, 0.0)

                def on_dl_progress(downloaded: int, total: int) -> None:
                    if total > 0:
                        GLib.idle_add(self._progress_set, downloaded / total)

                download_file(dl_url, dest, on_progress=on_dl_progress)

                GLib.idle_add(self.status_label.set_text, f"Installing {filename}...")
                GLib.idle_add(self._progress_start_pulse)
                nexus_meta = {
                    "game_domain": nxm["game_domain"],
                    "mod_id": nxm["mod_id"],
                    "file_id": nxm["file_id"],
                }
                try:
                    self.engine.install(dest, nexus_meta=nexus_meta)
                except ConflictError as ce:
                    confirmed = self._ask_conflict(ce.conflicts, filename)
                    if confirmed:
                        self.engine.install(dest, force=True, nexus_meta=nexus_meta)
                    else:
                        GLib.idle_add(self._progress_done)
                        GLib.idle_add(self.status_label.set_text, "Ready")
                        return

                GLib.idle_add(self._progress_done)
                GLib.idle_add(self.status_label.set_text, "Ready")
                GLib.idle_add(self._refresh_mods)
                GLib.idle_add(self._refresh_load_order)
                GLib.idle_add(self._toast, f"Installed: {filename}")
            except Exception as e:
                GLib.idle_add(self._progress_done)
                GLib.idle_add(self.status_label.set_text, "Ready")
                GLib.idle_add(self._toast, f"NXM import failed: {e}")

        threading.Thread(target=run, daemon=True).start()

    # ── Update check ──────────────────────────────────────────────────────────

    def _on_check_updates(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return
        api_key = get_nexus_api_key()
        if not api_key:
            self._show_api_key_dialog()
            return
        self._do_check_updates(api_key)

    def _do_check_updates(self, api_key: str):
        from nexus import check_update
        from installer import load_manifest

        def run():
            GLib.idle_add(self.status_label.set_text, "Checking for updates...")
            manifest = load_manifest()
            updates: list[tuple[str, str, str]] = []  # (mod_name, current_ver, latest_ver)
            errors: list[str] = []
            game_slug = self._game_slug

            for mod_name, entry in manifest.items():
                if entry.get("game") not in (None, game_slug):
                    continue
                nx = entry.get("nexus")
                if not nx:
                    continue
                try:
                    latest = check_update(
                        nx["game_domain"], nx["mod_id"], nx["file_id"], api_key
                    )
                    if latest:
                        updates.append((
                            mod_name,
                            str(nx.get("file_id", "?")),
                            latest.get("version") or str(latest.get("file_id", "?")),
                        ))
                except Exception as e:
                    errors.append(f"{mod_name}: {e}")

            GLib.idle_add(self.status_label.set_text, "Ready")
            GLib.idle_add(self._show_update_results, updates, errors)

        threading.Thread(target=run, daemon=True).start()

    def _show_update_results(self, updates: list, errors: list):
        if not updates and not errors:
            self._toast("All Nexus mods are up to date")
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

        dialog = Adw.MessageDialog(transient_for=self, heading="Update Check")
        dialog.set_body_use_markup(True)
        dialog.set_body("\n".join(lines))
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present()

    # ── Profiles ──────────────────────────────────────────────────────────────

    def _rebuild_profiles_popover(self, popover):
        """Rebuild popover content each time it opens."""
        import profiles as prof

        box = self._profiles_popover_box
        while child := box.get_first_child():
            box.remove(child)

        if not self.engine:
            no_game = Gtk.Label(label="Select a game first")
            no_game.add_css_class("dim-label")
            box.append(no_game)
            return

        slug = self._game_slug
        all_profiles = prof.load_all(slug)

        # ── Save section ──
        save_label = Gtk.Label(label="Save current as:")
        save_label.set_xalign(0)
        save_label.add_css_class("caption")
        box.append(save_label)

        save_entry = Gtk.Entry()
        save_entry.set_placeholder_text("Profile name")
        box.append(save_entry)

        save_btn = Gtk.Button(label="Save Profile")
        save_btn.add_css_class("suggested-action")

        def do_save(_btn):
            name = save_entry.get_text().strip()
            if not name:
                return
            active = [m["name"] for m in self.engine.list_mods() if m["active"]]
            order = self.engine.get_load_order() if self.engine.has_load_order else []
            prof.save(slug, name, active, order)
            self._toast(f"Saved profile: {name}")
            popover.popdown()

        save_btn.connect("clicked", do_save)
        box.append(save_btn)

        # ── Load / Delete section ──
        if all_profiles:
            sep = Gtk.Separator()
            sep.set_margin_top(4)
            sep.set_margin_bottom(4)
            box.append(sep)

            load_label = Gtk.Label(label="Saved profiles:")
            load_label.set_xalign(0)
            load_label.add_css_class("caption")
            box.append(load_label)

            profile_names = list(all_profiles.keys())
            dropdown = Gtk.DropDown.new_from_strings(profile_names)
            box.append(dropdown)

            btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            load_btn = Gtk.Button(label="Load")
            load_btn.set_hexpand(True)

            del_btn = Gtk.Button(label="Delete")
            del_btn.add_css_class("destructive-action")
            del_btn.set_hexpand(True)

            def do_load(_btn):
                name = profile_names[dropdown.get_selected()]
                popover.popdown()
                self._apply_profile(slug, name)

            def do_delete(_btn):
                name = profile_names[dropdown.get_selected()]
                prof.delete(slug, name)
                self._toast(f"Deleted profile: {name}")
                popover.popdown()

            load_btn.connect("clicked", do_load)
            del_btn.connect("clicked", do_delete)
            btn_row.append(load_btn)
            btn_row.append(del_btn)
            box.append(btn_row)

            def do_check_mods(_btn):
                name = profile_names[dropdown.get_selected()]
                popover.popdown()
                self._show_collection_mods_dialog(name, slug)

            check_btn = Gtk.Button(label="Check Mods")
            check_btn.connect("clicked", do_check_mods)
            box.append(check_btn)

        # ── Import modpack section ──
        sep2 = Gtk.Separator()
        sep2.set_margin_top(4)
        sep2.set_margin_bottom(4)
        box.append(sep2)

        import_label = Gtk.Label(label="Import Modpack from Nexus:")
        import_label.set_xalign(0)
        import_label.add_css_class("caption")
        box.append(import_label)

        import_entry = Gtk.Entry()
        import_entry.set_placeholder_text("https://www.nexusmods.com/…/collections/…")
        box.append(import_entry)

        import_btn = Gtk.Button(label="Import Modpack")

        def do_import(_btn):
            url = import_entry.get_text().strip()
            if not url:
                return
            popover.popdown()
            self._on_import_collection(url)

        import_btn.connect("clicked", do_import)
        box.append(import_btn)

    def _on_import_collection(self, url: str):
        if not self.engine:
            self._toast("Select a game first")
            return

        import re
        m = re.search(r"nexusmods\.com/(?:games/)?([^/]+)/collections/([a-z0-9]+)", url, re.I)
        if not m:
            self._toast("Invalid collection URL — expected nexusmods.com/…/collections/…")
            return

        collection_slug = m.group(2)
        slug = self._game_slug
        api_key = get_nexus_api_key()

        def run():
            collection_name = collection_slug
            collection_mods = None
            game_domain = None
            if api_key:
                from nexus import fetch_collection_graphql
                info = fetch_collection_graphql(collection_slug, api_key)
                if info:
                    collection_name = info.get("name") or collection_slug
                    collection_mods = info.get("mods")
                    game_domain = info.get("game_domain")

            import profiles as prof
            prof.save(slug, collection_name, [], [],
                      collection_mods=collection_mods,
                      collection_game_domain=game_domain)
            mod_count = len(collection_mods) if collection_mods else 0
            GLib.idle_add(self._show_collection_import_dialog, collection_name, mod_count)

        threading.Thread(target=run, daemon=True).start()

    def _show_collection_import_dialog(self, name: str, mod_count: int = 0):
        count_text = f" ({mod_count} mods)" if mod_count else ""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Modpack Profile Created",
            body=(
                f"Profile <b>{GLib.markup_escape_text(name)}</b>"
                f"{GLib.markup_escape_text(count_text)} has been saved.\n\n"
                "Nexus Mods requires downloading each mod individually. "
                "Install the mods via <b>NXM links</b> on the collection page, "
                "then use <b>Profiles/Modpacks → Check Mods</b> to see what's still missing."
            ),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present()

    def _get_installed_nexus_mod_ids(self, game_slug: str) -> set[int]:
        """Return set of nexus mod_ids installed for this game (from manifest)."""
        import re
        from installer import load_manifest
        manifest = load_manifest()
        ids: set[int] = set()
        for mod_name, entry in manifest.items():
            if entry.get("game") not in (None, game_slug):
                continue
            # Prefer stored nexus meta
            nexus = entry.get("nexus") or {}
            if nexus.get("mod_id"):
                ids.add(int(nexus["mod_id"]))
                continue
            # Fallback: extract from NexusMods archive filename pattern Name-MODID-ver-ts
            hit = re.search(r"-(\d{4,})-\d+(?:-\d+)*$", mod_name)
            if hit:
                ids.add(int(hit.group(1)))
        return ids

    def _show_collection_mods_dialog(self, profile_name: str, game_slug: str):
        import profiles as prof
        profile_data = prof.get(game_slug, profile_name) or {}
        collection_mods = profile_data.get("collection_mods", [])
        game_domain = profile_data.get("collection_game_domain", "")

        if not collection_mods:
            msg = Adw.MessageDialog(
                transient_for=self,
                heading="No mod list",
                body="This profile has no collection mod list. Re-import the collection URL to fetch it.",
            )
            msg.add_response("ok", "OK")
            msg.present()
            return

        installed_ids = self._get_installed_nexus_mod_ids(game_slug)
        installed_mods = [m for m in collection_mods if m["mod_id"] in installed_ids]
        missing_mods = [m for m in collection_mods if m["mod_id"] not in installed_ids]

        win = Adw.Window(transient_for=self, modal=True)
        win.set_title(
            f"{profile_name} — {len(installed_mods)}/{len(collection_mods)} installed"
        )
        win.set_default_size(540, 680)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        def _make_section(label_text: str, mods: list, css_class: str) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_margin_top(12)
            box.set_margin_bottom(4)

            header = Gtk.Label(label=label_text)
            header.set_xalign(0)
            header.add_css_class("heading")
            header.set_margin_bottom(6)
            box.append(header)

            listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listbox.add_css_class("boxed-list")

            for mod in sorted(mods, key=lambda m: m["name"].lower()):
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row_box.set_margin_start(8)
                row_box.set_margin_end(8)
                row_box.set_margin_top(6)
                row_box.set_margin_bottom(6)

                icon = Gtk.Image.new_from_icon_name(
                    "emblem-ok-symbolic" if css_class == "success" else "dialog-warning-symbolic"
                )
                icon.add_css_class(css_class)
                row_box.append(icon)

                name_label = Gtk.Label(label=mod["name"])
                name_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                name_label.set_hexpand(True)
                name_label.set_xalign(0)
                row_box.append(name_label)

                if mod.get("optional"):
                    opt = Gtk.Label(label="optional")
                    opt.add_css_class("dim-label")
                    opt.add_css_class("caption")
                    row_box.append(opt)

                if game_domain:
                    uri = f"https://www.nexusmods.com/{game_domain}/mods/{mod['mod_id']}"
                    link_btn = Gtk.LinkButton(uri=uri, label="Open")
                    link_btn.set_valign(Gtk.Align.CENTER)
                    row_box.append(link_btn)

                row = Gtk.ListBoxRow()
                row.set_child(row_box)
                listbox.append(row)

            box.append(listbox)
            return box

        if missing_mods:
            outer.append(_make_section(
                f"Missing ({len(missing_mods)})", missing_mods, "warning"
            ))
        if installed_mods:
            outer.append(_make_section(
                f"Installed ({len(installed_mods)})", installed_mods, "success"
            ))

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(outer)
        scroll.set_vexpand(True)
        toolbar_view.set_content(scroll)
        win.set_content(toolbar_view)
        win.present()

    def _apply_profile(self, slug: str, name: str):
        import profiles as prof
        data = prof.get(slug, name)
        if not data:
            self._toast(f"Profile not found: {name}")
            return

        active_set = set(data.get("active_mods", []))
        for mod in self.engine.list_mods():
            if mod["kind"] == "mod":
                if mod["name"] in active_set:
                    self.engine.enable_mod(mod["name"])
                else:
                    self.engine.disable_mod(mod["name"])

        order = data.get("load_order", [])
        if order and self.engine.has_load_order:
            self.engine.set_load_order(order)

        self._refresh_mods()
        self._refresh_load_order()
        self._toast(f"Loaded profile: {name}")

    # ── Header actions ────────────────────────────────────────────────────────

    def _on_check(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return
        # Engines expose verify() directly, or via .paths for Bethesda engines
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
            self.setup_btn.set_label("BepInEx ✓" if installed else "Install BepInEx")
            self.setup_btn.set_tooltip_text(
                "BepInEx is installed" if installed
                else "Download and install BepInEx into the game folder"
            )
        elif self.engine.has_script_extender:
            self.setup_btn.set_label("Setup SE")
            self.setup_btn.set_tooltip_text("Create the script extender launch wrapper")
        else:
            self.setup_btn.set_label("Setup SE")
            self.setup_btn.set_sensitive(False)

    def _on_setup_btn(self, _btn):
        if not self.engine:
            return
        if getattr(self.engine, "has_framework_setup", False):
            self._on_setup_bepinex()
        else:
            self._on_setup_se(None)

    def _on_setup_bepinex(self):
        if self.engine.is_framework_installed():
            # Already installed — show launch setup dialog instead
            self._show_bepinex_launch_dialog()
            return

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Install BepInEx",
            body=(
                "The latest BepInEx release will be downloaded from GitHub "
                f"and extracted to:\n<tt>{GLib.markup_escape_text(str(self.engine.game_root))}</tt>\n\n"
                "BepInEx is required for mods to work in this game."
            ),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("install", "Download & Install")
        dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("install")
        dialog.connect("response", lambda d, r: self._do_setup_bepinex() if r == "install" else None)
        dialog.present()

    def _show_bepinex_launch_dialog(self):
        try:
            launch_option = self.engine.setup_launch()
        except RuntimeError as e:
            self._toast(str(e))
            return

        copied = False
        try:
            self.get_display().get_clipboard().set(launch_option)
            copied = True
        except Exception:
            pass

        clipboard_note = "\nCopied to clipboard." if copied else ""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="BepInEx Launch Setup",
            body=(
                "BepInEx is installed. To activate mods, set this as your "
                "<b>Steam Launch Option</b> "
                "(right-click game → Properties → General):\n\n"
                f"<tt>{GLib.markup_escape_text(launch_option)}</tt>"
                f"{clipboard_note}"
            ),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("ok", "OK")
        dialog.present()

    def _do_setup_bepinex(self):
        def run():
            GLib.idle_add(self.status_label.set_text, "Fetching BepInEx release info...")
            GLib.idle_add(self._progress_set, 0.0)
            try:
                def on_progress(downloaded, total):
                    if total > 0:
                        GLib.idle_add(self._progress_set, downloaded / total)
                    GLib.idle_add(
                        self.status_label.set_text,
                        f"Downloading BepInEx... {downloaded // 1024} KB"
                        + (f" / {total // 1024} KB" if total > 0 else ""),
                    )

                version = self.engine.setup_framework(on_progress=on_progress)

                GLib.idle_add(self._progress_start_pulse)
                GLib.idle_add(self.status_label.set_text, "Extracting BepInEx...")
                # setup_framework already extracted — just update UI
                GLib.idle_add(self._progress_done)
                GLib.idle_add(self.status_label.set_text, "Ready")
                GLib.idle_add(self._update_setup_btn)
                GLib.idle_add(self._refresh_mods)
                GLib.idle_add(self._show_bepinex_launch_dialog)
                GLib.idle_add(self._toast, f"BepInEx {version} installed successfully")
            except Exception as e:
                GLib.idle_add(self._progress_done)
                GLib.idle_add(self.status_label.set_text, "Ready")
                GLib.idle_add(self._toast, f"BepInEx install failed: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _on_setup_se(self, _btn):
        if not self.engine or not self.engine.has_script_extender:
            self._toast("No script extender for this game")
            return
        try:
            script_path = self.engine.setup_script_extender()
        except Exception as e:
            self._toast(f"Setup failed: {e}")
            return

        launch_option = f'"{script_path}" %command%'

        copied = False
        try:
            self.get_display().get_clipboard().set(launch_option)
            copied = True
        except Exception:
            pass

        clipboard_note = "\nThe text has been copied to your clipboard." if copied else ""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Script Extender Setup Complete",
            body=(
                "A launch script was created. Add the following to your game's "
                "<b>Steam Launch Options</b> (right-click game → Properties → General):\n\n"
                f"<tt>{GLib.markup_escape_text(launch_option)}</tt>"
                f"{clipboard_note}"
            ),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("ok", "OK")
        dialog.present()

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _toast(self, message: str):
        # Adw.Toast.title is Pango markup — escape special chars (&, <, >) in messages
        toast = Adw.Toast(title=GLib.markup_escape_text(message))
        self.toast_overlay.add_toast(toast)


# GTK4 helper — create a Gio.ListStore from a filter (needed for FileDialog)
def Gio_ListStore_from_filter(f: Gtk.FileFilter):
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    return store


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
