"""
GTK4 + libadwaita GUI for Linux Mod Manager.
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
from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Pango

# Bootstrap paths
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "engines"))

from config import (
    load_profile, GAMES_DIR, ARCHIVES_DIR,
    get_steam_root, get_steam_candidates, save_steam_root,
    get_nexus_api_key, save_nexus_api_key,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_engine(game: str):
    profile = load_profile(game)
    profile["slug"] = game
    if profile["engine"] == "bethesda":
        from bethesda import BethesdaEngine
        return BethesdaEngine(profile)
    raise ValueError(f"Engine '{profile['engine']}' not yet implemented")


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

        if mod.get("kind") == "se_plugin":
            sub = Gtk.Label(label="SE Plugin")
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
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Linux Mod Manager")
        self.set_default_size(900, 600)

        self.engine = None
        self.games = available_games()
        self._installing = False
        self._game_slug = None

        self._build_ui()
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

        # Game dropdown
        game_names = [name for _, name in self.games]
        self.game_dropdown = Gtk.DropDown.new_from_strings(game_names)
        self._game_changed_handler = self.game_dropdown.connect("notify::selected", self._on_game_changed)
        header.set_title_widget(self.game_dropdown)

        # Header buttons
        check_btn = Gtk.Button(label="Check")
        check_btn.connect("clicked", self._on_check)
        header.pack_end(check_btn)

        setup_btn = Gtk.Button(label="Setup SE")
        setup_btn.connect("clicked", self._on_setup_se)
        header.pack_end(setup_btn)

        help_btn = Gtk.Button()
        help_btn.set_icon_name("help-about-symbolic")
        help_btn.set_tooltip_text("Help")
        help_btn.connect("clicked", self._on_help)
        header.pack_start(help_btn)

        profiles_btn = Gtk.Button()
        profiles_btn.set_icon_name("bookmark-new-symbolic")
        profiles_btn.set_tooltip_text("Profiles")
        profiles_btn.connect("clicked", self._on_profiles)
        header.pack_start(profiles_btn)

        # Content: horizontal split
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.content_box.set_vexpand(True)
        root.append(self.content_box)

        # Left panel — installed mods
        self.content_box.append(self._build_mods_panel())

        # Right panel — load order (added dynamically based on engine)
        self.load_order_panel = self._build_load_order_panel()

        # Status bar
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.add_css_class("dim-label")
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.set_margin_top(4)
        self.status_label.set_margin_bottom(4)
        self.status_label.set_xalign(0)
        root.append(self.status_label)

    def _build_mods_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.set_hexpand(True)
        panel.set_size_request(360, -1)

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

    def _select_game(self, index: int):
        slug, name = self.games[index]
        try:
            self.engine = load_engine(slug)
        except Exception as e:
            self._toast(f"Failed to load engine: {e}")
            return

        self._game_slug = slug
        self.set_title(f"Linux Mod Manager — {name}")
        self._update_load_order_panel()
        self._refresh_mods()
        self._refresh_load_order()

    def _on_game_changed(self, dropdown, _param):
        self._select_game(dropdown.get_selected())

    def _show_game_picker(self):
        if not self.games:
            self._toast("No game profiles found in games/")
            return

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Select a Game",
            body="Which game do you want to manage?",
        )
        for slug, name in self.games:
            dialog.add_response(slug, name)
        dialog.connect("response", self._on_game_picker_response)
        dialog.present()

    def _on_game_picker_response(self, dialog, response_id: str):
        for idx, (slug, _name) in enumerate(self.games):
            if slug == response_id:
                # Block notify signal to avoid double-load when syncing dropdown
                self.game_dropdown.handler_block(self._game_changed_handler)
                self.game_dropdown.set_selected(idx)
                self.game_dropdown.handler_unblock(self._game_changed_handler)
                self._select_game(idx)
                break

    # ── Steam path setup ──────────────────────────────────────────────────────

    def _init_steam_path(self):
        if get_steam_root() is None:
            self._show_steam_path_dialog(get_steam_candidates())
        else:
            self._show_game_picker()

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
            self._show_game_picker()
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
                "They were not installed through this manager — remove them manually if needed."
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
            for i, path in enumerate(paths):
                GLib.idle_add(
                    self.status_label.set_text,
                    f"Installing {path.name} ({i+1}/{len(paths)})..."
                )
                try:
                    self.engine.install(path)
                except Exception as e:
                    GLib.idle_add(self._toast, f"Failed: {path.name} — {e}")

            self._installing = False
            GLib.idle_add(self.status_label.set_text, "Ready")
            GLib.idle_add(self._refresh_mods)
            GLib.idle_add(self._refresh_load_order)

        threading.Thread(target=run, daemon=True).start()

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
                download_file(dl_url, dest)

                GLib.idle_add(self.status_label.set_text, f"Installing {filename}...")
                self.engine.install(dest)

                GLib.idle_add(self.status_label.set_text, "Ready")
                GLib.idle_add(self._refresh_mods)
                GLib.idle_add(self._refresh_load_order)
                GLib.idle_add(self._toast, f"Installed: {filename}")
            except Exception as e:
                GLib.idle_add(self.status_label.set_text, "Ready")
                GLib.idle_add(self._toast, f"NXM import failed: {e}")

        threading.Thread(target=run, daemon=True).start()

    # ── Profiles ──────────────────────────────────────────────────────────────

    def _on_profiles(self, _btn):
        if not self.engine:
            self._toast("Select a game first")
            return

        import profiles as prof
        slug = self._game_slug
        all_profiles = prof.load_all(slug)

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Mod Profiles",
            body="Save current state as a named profile, or load a saved one.",
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_bottom(8)

        # Save section
        save_label = Gtk.Label(label="Save current as:")
        save_label.set_xalign(0)
        box.append(save_label)

        save_entry = Gtk.Entry()
        save_entry.set_placeholder_text("Profile name")
        box.append(save_entry)

        save_btn = Gtk.Button(label="Save Profile")
        save_btn.add_css_class("suggested-action")
        box.append(save_btn)

        # Load section
        if all_profiles:
            sep = Gtk.Separator()
            sep.set_margin_top(4)
            box.append(sep)

            load_label = Gtk.Label(label="Load / Delete:")
            load_label.set_xalign(0)
            box.append(load_label)

            profile_names = list(all_profiles.keys())
            dropdown = Gtk.DropDown.new_from_strings(profile_names)
            box.append(dropdown)

            load_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            load_btn = Gtk.Button(label="Load")
            load_btn.set_hexpand(True)
            load_row.append(load_btn)

            del_btn = Gtk.Button(label="Delete")
            del_btn.add_css_class("destructive-action")
            del_btn.set_hexpand(True)
            load_row.append(del_btn)

            box.append(load_row)

            def do_load(_btn):
                name = profile_names[dropdown.get_selected()]
                self._apply_profile(slug, name)
                dialog.close()

            def do_delete(_btn):
                name = profile_names[dropdown.get_selected()]
                prof.delete(slug, name)
                self._toast(f"Deleted profile: {name}")
                dialog.close()

            load_btn.connect("clicked", do_load)
            del_btn.connect("clicked", do_delete)

        def do_save(_btn):
            name = save_entry.get_text().strip()
            if not name:
                return
            active = [m["name"] for m in self.engine.list_mods() if m["active"]]
            order = self.engine.get_load_order() if self.engine.has_load_order else []
            prof.save(slug, name, active, order)
            self._toast(f"Saved profile: {name}")
            dialog.close()

        save_btn.connect("clicked", do_save)

        dialog.set_extra_child(box)
        dialog.add_response("close", "Close")
        dialog.present()

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
        warnings = self.engine.paths.verify()
        if warnings:
            self._toast(f"⚠ {warnings[0]}" + (f" (+{len(warnings)-1} more)" if len(warnings) > 1 else ""))
        else:
            self._toast("✓ All paths verified")

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
        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)


# GTK4 helper — create a Gio.ListStore from a filter (needed for FileDialog)
def Gio_ListStore_from_filter(f: Gtk.FileFilter):
    from gi.repository import Gio
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    return store


# ── Application ───────────────────────────────────────────────────────────────

class ModManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.linuxmodmanager")
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        win = ModManagerWindow(app)
        win.present()


def main():
    app = ModManagerApp()
    app.run(sys.argv)
