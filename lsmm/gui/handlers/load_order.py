"""Load order panel builder and management handlers."""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from lsmm.gui.widgets.plugin_row import PluginRow


def build_load_order_panel(win) -> Gtk.Box:
    """Build the load order column panel, setting win.plugins_list."""
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

    win.plugins_list = Gtk.ListBox()
    win.plugins_list.set_selection_mode(Gtk.SelectionMode.NONE)
    win.plugins_list.add_css_class("boxed-list")
    win.plugins_list.set_margin_start(12)
    win.plugins_list.set_margin_end(12)
    scroll.set_child(win.plugins_list)

    save_btn = Gtk.Button(label="Save Order")
    save_btn.set_margin_start(12)
    save_btn.set_margin_end(12)
    save_btn.set_margin_top(8)
    save_btn.set_margin_bottom(12)
    save_btn.connect("clicked", lambda _: save_order(win))
    inner.append(save_btn)

    return panel


def refresh_load_order(win):
    if not win.engine or not win.engine.has_load_order:
        return
    while child := win.plugins_list.get_first_child():
        win.plugins_list.remove(child)
    for i, name in enumerate(win.engine.get_load_order()):
        win.plugins_list.append(PluginRow(name, i, lambda dn, tn: move_plugin(win, dn, tn)))


def save_order(win):
    order = []
    child = win.plugins_list.get_first_child()
    while child:
        if isinstance(child, PluginRow):
            order.append(child.plugin_name)
        child = child.get_next_sibling()
    win.engine.set_load_order(order)
    win._toast("Load order saved")


def move_plugin(win, dragged_name: str, target_name: str):
    order = []
    child = win.plugins_list.get_first_child()
    while child:
        if isinstance(child, PluginRow):
            order.append(child.plugin_name)
        child = child.get_next_sibling()

    if dragged_name not in order or target_name not in order or dragged_name == target_name:
        return

    order.remove(dragged_name)
    order.insert(order.index(target_name), dragged_name)

    while child := win.plugins_list.get_first_child():
        win.plugins_list.remove(child)
    for i, name in enumerate(order):
        win.plugins_list.append(PluginRow(name, i, lambda dn, tn: move_plugin(win, dn, tn)))
