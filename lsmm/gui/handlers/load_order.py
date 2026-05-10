"""Load order panel builder and management handlers."""

import threading

from lsmm.core.loot import detect_loot, sort_with_loot

_LOOT_INSTALL_HINT = (
    "LOOT not found — install via package manager or Flatpak (io.github.loot.loot)"
)


def _glib():
    import gi as _gi
    _gi.require_version("Gtk", "4.0")
    from gi.repository import GLib as _GLib
    return _GLib


def build_load_order_panel(win):
    """Build the load order column panel, setting win.plugins_list."""
    import gi as _gi
    _gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

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

    win.plugins_list = Gtk.ListBox()
    win.plugins_list.set_selection_mode(Gtk.SelectionMode.NONE)
    win.plugins_list.add_css_class("boxed-list")
    win.plugins_list.set_margin_start(12)
    win.plugins_list.set_margin_end(12)
    scroll.set_child(win.plugins_list)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_margin_start(12)
    btn_box.set_margin_end(12)
    btn_box.set_margin_top(8)
    btn_box.set_margin_bottom(12)

    save_btn = Gtk.Button(label="Save Order")
    save_btn.set_hexpand(True)
    save_btn.connect("clicked", lambda _: save_order(win))
    btn_box.append(save_btn)

    loot_cmd = detect_loot()
    loot_btn = Gtk.Button(label="Sort with LOOT")
    loot_btn.set_hexpand(True)
    loot_btn.set_sensitive(bool(loot_cmd))
    loot_btn.set_tooltip_text("Sort load order with LOOT" if loot_cmd else _LOOT_INSTALL_HINT)
    loot_btn.connect("clicked", lambda _: do_sort_with_loot(win))
    btn_box.append(loot_btn)

    inner.append(btn_box)

    return panel


def _get_order(win) -> list:
    from lsmm.gui.widgets.plugin_row import PluginRow
    order = []
    child = win.plugins_list.get_first_child()
    while child:
        if isinstance(child, PluginRow):
            order.append(child.plugin_name)
        child = child.get_next_sibling()
    return order


def _rebuild(win, order: list) -> None:
    from lsmm.gui.widgets.plugin_row import PluginRow
    while child := win.plugins_list.get_first_child():
        win.plugins_list.remove(child)
    for i, name in enumerate(order):
        win.plugins_list.append(PluginRow(
            name, i,
            on_move=lambda dn, tn: move_plugin(win, dn, tn),
            on_step=lambda n, d: step_plugin(win, n, d),
        ))


def refresh_load_order(win):
    if not win.engine or not win.engine.has_load_order:
        return
    _rebuild(win, win.engine.get_load_order())


def save_order(win):
    win.engine.set_load_order(_get_order(win))
    win._toast("Load order saved")


def do_sort_with_loot(win) -> None:
    """Run LOOT sort in a background thread; refresh load order on success."""
    def run():
        try:
            sort_with_loot(win.engine.profile, win.engine.paths.game_root)
            _glib().idle_add(win._refresh_load_order)
        except Exception as e:
            _glib().idle_add(win._toast, f"LOOT sort failed: {e}")

    threading.Thread(target=run, daemon=True).start()


def move_plugin(win, dragged_name: str, target_name: str):
    order = _get_order(win)
    if dragged_name not in order or target_name not in order or dragged_name == target_name:
        return
    order.remove(dragged_name)
    order.insert(order.index(target_name), dragged_name)
    _rebuild(win, order)


def step_plugin(win, name: str, delta: int):
    order = _get_order(win)
    if name not in order:
        return
    idx = order.index(name)
    new_idx = max(0, min(len(order) - 1, idx + delta))
    if new_idx == idx:
        return
    order.pop(idx)
    order.insert(new_idx, name)
    _rebuild(win, order)
