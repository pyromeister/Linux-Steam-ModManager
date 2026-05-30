"""Mod Engine tab builder and handlers."""

import html
import threading
from pathlib import Path


def _ver_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def _update_needed(installed: str, latest: str) -> bool:
    """True only when latest is strictly newer than installed."""
    return _ver_tuple(latest) > _ver_tuple(installed)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from lsmm.core.script_extender import fetch_github_latest_tag
from lsmm.core.config import get_path_overrides, save_path_overrides
from lsmm.core.utils import load_engine as _load_engine


def abbrev_path(path: Path) -> str:
    parts = path.parts
    return ("…/" + "/".join(parts[-3:])) if len(parts) > 3 else str(path)


def set_row(row: Adw.ActionRow, text: str, visible: bool = True) -> None:
    row.set_subtitle(text)
    row.set_visible(visible)


def set_se_row(row: Adw.ActionRow, val: Gtk.Label, text: str, visible: bool = True) -> None:
    val.set_text(text)
    row.set_visible(visible)


def set_version_label(lbl: Gtk.Label, text: str) -> None:
    if "available" in text:
        markup = f'<span foreground="#e5a50a">{html.escape(text)}</span>'
    elif text.startswith("✓"):
        markup = f'<span foreground="#2ec27e">{html.escape(text)}</span>'
    else:
        markup = html.escape(text)
    lbl.set_markup(markup)


def build_mod_engine_tab(win) -> Gtk.Widget:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

    win._mod_engine_placeholder = Adw.StatusPage()
    win._mod_engine_placeholder.set_icon_name("application-x-executable-symbolic")
    win._mod_engine_placeholder.set_title("No game selected")
    win._mod_engine_placeholder.set_description("Select a game from the Games menu")
    outer.append(win._mod_engine_placeholder)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    scroll.set_visible(False)

    win._mod_engine_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    win._mod_engine_content.set_margin_start(16)
    win._mod_engine_content.set_margin_end(16)
    win._mod_engine_content.set_margin_top(16)
    win._mod_engine_content.set_margin_bottom(16)
    scroll.set_child(win._mod_engine_content)

    # ── Panel header: "Mod Engine" fixed left + "Game · SE" right ───────────
    panel_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    panel_hdr.set_margin_bottom(4)
    _hdr_title = Gtk.Label(label="Mod Engine")
    _hdr_title.add_css_class("heading")
    _hdr_title.set_hexpand(True)
    _hdr_title.set_xalign(0)
    panel_hdr.append(_hdr_title)
    win._engine_sub_label = Gtk.Label()
    win._engine_sub_label.add_css_class("dim-label")
    win._engine_sub_label.add_css_class("caption")
    panel_hdr.append(win._engine_sub_label)
    win._mod_engine_content.append(panel_hdr)

    # ── Script Extender / Framework section ──────────────────────────────
    win._se_group = Adw.PreferencesGroup()
    win._mod_engine_content.append(win._se_group)

    def _make_se_info_row(title):
        row = Adw.ActionRow()
        row.set_title(title)
        lbl = Gtk.Label()
        lbl.set_halign(Gtk.Align.END)
        lbl.set_use_markup(True)
        lbl.add_css_class("dim-label")
        row.add_suffix(lbl)
        return row, lbl

    win._se_version_row, win._se_version_val = _make_se_info_row("Version")
    win._se_version_val.remove_css_class("dim-label")
    win._se_group.add(win._se_version_row)

    win._se_loader_row, win._se_loader_val = _make_se_info_row("Loader")
    win._se_group.add(win._se_loader_row)

    win._se_plugins_dir_row, win._se_plugins_val = _make_se_info_row("Plugins dir")
    win._se_group.add(win._se_plugins_dir_row)

    win._se_launch_row, win._se_launch_val = _make_se_info_row("Steam launch")
    win._se_group.add(win._se_launch_row)

    # ── Action buttons ────────────────────────────────────────────────────
    btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    win.setup_btn = Gtk.Button()
    win.setup_btn.connect("clicked", lambda btn: win._on_setup_btn(btn))
    btn_row.append(win.setup_btn)

    win._ensure_ini_btn = Gtk.Button(label="Ensure INI Settings")
    win._ensure_ini_btn.set_tooltip_text("Add bInvalidateOlderFiles=1 to the game's Custom INI")
    win._ensure_ini_btn.connect("clicked", lambda btn: on_ensure_ini(win, btn))
    win._ensure_ini_btn.set_visible(False)
    btn_row.append(win._ensure_ini_btn)

    win._uninstall_fw_btn = Gtk.Button(label="Uninstall")
    win._uninstall_fw_btn.set_tooltip_text("Remove mod engine files from game directory")
    win._uninstall_fw_btn.add_css_class("destructive-action")
    win._uninstall_fw_btn.connect("clicked", lambda btn: on_uninstall_framework(win, btn))
    win._uninstall_fw_btn.set_visible(False)
    btn_row.append(win._uninstall_fw_btn)

    win._uninstall_se_btn = Gtk.Button(label="Uninstall SE")
    win._uninstall_se_btn.set_tooltip_text("Remove script extender files from game directory")
    win._uninstall_se_btn.add_css_class("destructive-action")
    win._uninstall_se_btn.connect("clicked", lambda btn: on_uninstall_se(win, btn))
    win._uninstall_se_btn.set_visible(False)
    btn_row.append(win._uninstall_se_btn)

    verify_btn = Gtk.Button(label="Verify Paths")
    verify_btn.set_tooltip_text("Check that game and script extender paths exist")
    verify_btn.connect("clicked", lambda btn: on_verify_paths_btn(win, btn))
    btn_row.append(verify_btn)
    win._mod_engine_content.append(btn_row)

    # ── Installation Paths section ────────────────────────────────────────
    win._paths_group = Adw.PreferencesGroup()
    win._paths_group.set_title("Installation Paths")
    edit_paths_btn = Gtk.Button(label="Edit")
    edit_paths_btn.add_css_class("flat")
    edit_paths_btn.set_valign(Gtk.Align.CENTER)
    edit_paths_btn.connect("clicked", lambda btn: on_edit_paths(win, btn))
    win._paths_group.set_header_suffix(edit_paths_btn)
    win._mod_engine_content.append(win._paths_group)

    def _make_path_row(title):
        row = Adw.ActionRow()
        row.set_title(title)
        badge = Gtk.Label(label="auto")
        badge.add_css_class("dim-label")
        badge.add_css_class("caption")
        badge.set_margin_start(4)
        row.add_suffix(badge)
        return row

    win._path_game_root_row = _make_path_row("Game root")
    win._paths_group.add(win._path_game_root_row)

    win._path_mods_dir_row = _make_path_row("Mods dir")
    win._paths_group.add(win._path_mods_dir_row)

    win._path_data_dir_row = _make_path_row("Data dir")
    win._paths_group.add(win._path_data_dir_row)

    win._path_proton_row = _make_path_row("Proton prefix")
    win._paths_group.add(win._path_proton_row)

    win._path_plugins_txt_row = _make_path_row("Plugins.txt")
    win._paths_group.add(win._path_plugins_txt_row)

    outer.append(scroll)
    win._mod_engine_scroll = scroll
    return outer


def refresh_mod_engine_tab(win):
    if not win.engine:
        win._mod_engine_placeholder.set_visible(True)
        win._mod_engine_scroll.set_visible(False)
        return

    win._mod_engine_placeholder.set_visible(False)
    win._mod_engine_scroll.set_visible(True)
    win._ensure_ini_btn.set_visible(hasattr(win.engine, "ensure_ini"))
    _se_loader = getattr(getattr(win.engine, "paths", None), "se_loader", None)
    win._uninstall_se_btn.set_visible(bool(_se_loader and _se_loader.exists()))
    _fw_installed = (getattr(win.engine, "has_framework_setup", False)
                     and win.engine.is_framework_installed())
    win._uninstall_fw_btn.set_visible(_fw_installed)
    win._update_setup_btn()

    game_name = next((n for s, n in win.games if s == win._game_slug), win._game_slug or "")

    # ── SE / framework info rows ──────────────────────────────────────────
    paths = getattr(win.engine, "paths", None)
    se = getattr(paths, "script_extender", None) if paths else None
    game_root = getattr(paths, "game_root", None)
    if getattr(win.engine, "has_framework_setup", False):
        from lsmm.core.installer import load_manifest
        fw = getattr(win.engine, "framework_name", "BepInEx")
        fw_cfg = getattr(win.engine, "framework_config", {})
        win._engine_sub_label.set_text(f"{game_name} · {fw}")
        win._se_group.set_title(fw)
        installed = win.engine.is_framework_installed()
        ver = load_manifest().get(fw, {}).get("nexus", {}).get("version") or ""
        win._se_version_row.set_title("Version")
        win._se_version_row.set_visible(True)
        github_repo = fw_cfg.get("github_repo")
        slug = win._game_slug or ""
        ver_prefix = f"v{ver.lstrip('v')}" if ver else "Installed"
        if not installed:
            set_version_label(win._se_version_val, "Not installed")
        elif github_repo:
            cached_ver = win._se_version_cache.get(slug)
            if cached_ver:
                set_version_label(win._se_version_val, cached_ver)
            elif slug not in win._se_check_in_flight:
                set_version_label(win._se_version_val, f"✓ {ver_prefix} — checking…")
                win._se_check_in_flight.add(slug)
                val_ref = win._se_version_val

                def _fw_check(repo=github_repo, lbl=val_ref, s=slug, vp=ver_prefix):
                    latest = fetch_github_latest_tag(repo)
                    installed_raw = vp.lstrip("v") if vp != "Installed" else None
                    update_avail = False
                    if latest:
                        if installed_raw and _update_needed(installed_raw, latest):
                            text = f"✓ {vp} — v{latest} available"
                            update_avail = True
                        elif installed_raw:
                            text = f"✓ {vp} — up to date"
                        else:
                            text = f"✓ Installed — v{latest} available"
                            update_avail = True
                    else:
                        text = f"✓ {vp}"
                    win._se_version_cache[s] = text
                    win._se_check_in_flight.discard(s)
                    if update_avail:
                        win._fw_update_available.add(s)
                    else:
                        win._fw_update_available.discard(s)

                    def _update(t=text, lbl=lbl, s=s):
                        if win._game_slug == s:
                            set_version_label(lbl, t)
                            win._update_setup_btn()
                        return False
                    GLib.idle_add(_update)
                threading.Thread(target=_fw_check, daemon=True).start()
            else:
                set_version_label(win._se_version_val, f"✓ {ver_prefix} — checking…")
        else:
            set_version_label(win._se_version_val, f"✓ {ver_prefix}" if installed else "Not installed")
        exe_name = fw_cfg.get("executable", fw)
        exe_path = (win.engine.game_root / exe_name) if exe_name else None
        win._se_loader_row.set_title("Executable")
        if exe_path:
            set_se_row(
                win._se_loader_row, win._se_loader_val,
                abbrev_path(exe_path) + ("  ✓" if exe_path.exists() else "  ✗ Not found"),
            )
        else:
            set_se_row(win._se_loader_row, win._se_loader_val, "", False)
        launch_name = fw_cfg.get("launch_script")
        launch_path = (win.engine.game_root / launch_name) if launch_name else None
        win._se_launch_row.set_title("Launch script")
        if launch_path and launch_path != exe_path:
            set_se_row(
                win._se_launch_row, win._se_launch_val,
                abbrev_path(launch_path) + ("  ✓" if launch_path.exists() else "  ✗ Not found"),
            )
        else:
            set_se_row(win._se_launch_row, win._se_launch_val, "", False)
        set_se_row(win._se_plugins_dir_row, win._se_plugins_val, "", False)
    elif se:
        se_name = se.get("name", "Script Extender")
        win._engine_sub_label.set_text(f"{game_name} · {se_name}")
        win._se_group.set_title(se_name)
        win._se_version_row.set_title("Version")
        win._se_loader_row.set_title("Loader")
        win._se_launch_row.set_title("Steam launch")
        se_loader = getattr(paths, "se_loader", None)
        se_installed = bool(se_loader and se_loader.exists())
        slug = win._game_slug or ""
        installed_ver = getattr(win.engine, "get_se_installed_version", lambda: None)()
        ver_prefix = f"v{installed_ver}" if installed_ver else "Installed"
        cached_ver = win._se_version_cache.get(slug)
        if not se_installed:
            win._se_version_row.set_visible(True)
            set_version_label(win._se_version_val, "✗ Not installed")
        elif cached_ver:
            win._se_version_row.set_visible(True)
            set_version_label(win._se_version_val, cached_ver)
        elif slug not in win._se_check_in_flight:
            win._se_version_row.set_visible(True)
            set_version_label(win._se_version_val, f"✓ {ver_prefix} — checking…")
            win._se_check_in_flight.add(slug)
            engine_ref = win.engine
            val_ref = win._se_version_val

            def _check(eng=engine_ref, lbl=val_ref, s=slug, vp=ver_prefix):
                info = getattr(eng, "get_se_latest_info", lambda: None)()
                if info:
                    latest = info[0].lstrip("v")
                    installed_raw = vp.lstrip("v") if vp != "Installed" else None
                    if installed_raw and _update_needed(installed_raw, latest):
                        text = f"✓ {vp} — v{latest} available"
                    elif installed_raw:
                        text = f"✓ {vp} — up to date"
                    else:
                        text = f"✓ Installed — v{latest} available"
                else:
                    text = f"✓ {vp}"
                win._se_version_cache[s] = text
                win._se_check_in_flight.discard(s)

                def _update(t=text, lbl=lbl, s=s):
                    if win._game_slug == s:
                        set_version_label(lbl, t)
                    return False
                GLib.idle_add(_update)
            threading.Thread(target=_check, daemon=True).start()
        set_se_row(win._se_loader_row, win._se_loader_val,
                   abbrev_path(se_loader) if se_loader else "", bool(se_loader))
        se_plugins = getattr(paths, "se_plugins_dir", None)
        set_se_row(
            win._se_plugins_dir_row, win._se_plugins_val,
            abbrev_path(se_plugins) if se_plugins else "",
            bool(se_plugins),
        )
        launch_sh = (game_root / "se_launch.sh") if game_root else None
        if launch_sh:
            set_se_row(
                win._se_launch_row, win._se_launch_val,
                abbrev_path(launch_sh) + ("  ✓" if launch_sh.exists() else "  ✗ Not found — run Setup"),
            )
        else:
            set_se_row(win._se_launch_row, win._se_launch_val, "not set up — run Setup below")
    else:
        win._engine_sub_label.set_text(f"{game_name} · Folder mods")
        win._se_group.set_title("No Script Extender")
        set_se_row(win._se_version_row, win._se_version_val, "Folder-based mod loading")
        set_se_row(win._se_loader_row, win._se_loader_val, "", False)
        set_se_row(win._se_plugins_dir_row, win._se_plugins_val, "", False)
        set_se_row(win._se_launch_row, win._se_launch_val, "", False)

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
            win._path_game_root_row.set_subtitle(
                abbrev_path(game_root) + ("  ✓" if exists else "  ✗ Not found")
            )
        win._path_game_root_row.set_visible(bool(game_root))
        mods_dir = getattr(paths, "mods_dir", None) or getattr(win.engine, "mods_dir", None)
        if mods_dir:
            exists = mods_dir.exists()
            win._path_mods_dir_row.set_subtitle(
                abbrev_path(mods_dir)
                + ("  ✓" if exists else "  — created on first install")
            )
        win._path_mods_dir_row.set_visible(bool(mods_dir))
        if data_dir:
            exists = data_dir.exists()
            win._path_data_dir_row.set_subtitle(
                abbrev_path(data_dir) + ("  ✓" if exists else "  ✗ Not found")
            )
        win._path_data_dir_row.set_visible(bool(data_dir))
        if proton:
            exists = proton.exists()
            win._path_proton_row.set_subtitle(
                abbrev_path(proton) + ("  ✓" if exists else "  — launch game once to create")
            )
        win._path_proton_row.set_visible(bool(proton))
        if plugins_txt:
            win._path_plugins_txt_row.set_subtitle(abbrev_path(plugins_txt))
            win._path_plugins_txt_row.set_visible(True)
        else:
            win._path_plugins_txt_row.set_visible(False)
        win._paths_group.set_visible(True)
    else:
        win._paths_group.set_visible(False)


def on_ensure_ini(win, _btn):
    if not win.engine or not hasattr(win.engine, "ensure_ini"):
        return
    try:
        win.engine.ensure_ini()
        win._toast("✓ INI settings applied")
    except Exception as e:
        win._toast(f"INI update failed: {e}")


def on_uninstall_framework(win, _btn):
    if not win.engine or not getattr(win.engine, "has_framework_setup", False):
        return
    fw = getattr(win.engine, "framework_name", "BepInEx")
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading=f"Uninstall {fw}?",
        body=f"This will remove all {fw} files from the game directory. Mods that depend on {fw} will stop working.",
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("uninstall", f"Uninstall {fw}")
    dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def _on_response(_d, response):
        if response != "uninstall":
            return
        try:
            win.engine.uninstall(fw)
            win._se_version_cache.pop(win._game_slug or "", None)
            win._se_check_in_flight.discard(win._game_slug or "")
            win._refresh_all()
            win._toast(f"✓ {fw} removed")
        except Exception as e:
            win._toast(f"Uninstall failed: {e}")

    dialog.connect("response", _on_response)
    dialog.present()


def on_uninstall_se(win, _btn):
    if not win.engine or not hasattr(win.engine, "uninstall_script_extender"):
        return
    se = win.engine.profile.get("script_extender", {})
    se_name = se.get("name", "Script Extender")
    dialog = Adw.MessageDialog(
        transient_for=win,
        heading=f"Uninstall {se_name}?",
        body=f"This will remove all {se_name} files from the game directory. "
             f"Mods that depend on {se_name} will stop working.",
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("uninstall", f"Uninstall {se_name}")
    dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def _on_response(_d, response):
        if response != "uninstall":
            return
        try:
            win.engine.uninstall_script_extender()
            win._se_version_cache.pop(win._game_slug or "", None)
            win._se_check_in_flight.discard(win._game_slug or "")
            win._refresh_all()
            win._toast(f"✓ {se_name} removed")
        except Exception as e:
            win._toast(f"Uninstall failed: {e}")

    dialog.connect("response", _on_response)
    dialog.present()


def show_verify_warnings(win, warnings: list) -> None:
    if warnings:
        win._toast(f"⚠ {warnings[0]}" + (f" (+{len(warnings)-1} more)" if len(warnings) > 1 else ""))
    else:
        win._toast("✓ All paths verified")


def on_verify_paths_btn(win, _btn):
    if not win.engine:
        return
    if hasattr(win.engine, "paths"):
        show_verify_warnings(win, win.engine.paths.verify())
    else:
        win._toast("Verify not supported for this engine")


def on_edit_paths(win, _btn):
    if not win.engine:
        return
    app_id = str(win.engine.profile.get("steam_app_id", ""))
    paths = getattr(win.engine, "paths", None)
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

    entries: dict = {}

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
            win.engine = _load_engine(win._game_slug)
        except Exception:
            pass
        win._refresh_all()
        win._update_action_sensitivity()
        win._update_setup_btn()
        dialog.close()
        win._toast("Path overrides saved")

    save_row.connect("activated", _on_save)
    action_grp.add(save_row)

    dialog.present(win)
