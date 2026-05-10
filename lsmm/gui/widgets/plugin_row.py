import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GObject, Gtk, Pango


class PluginRow(Gtk.ListBoxRow):
    def __init__(self, name: str, index: int, on_move=None, on_step=None):
        super().__init__()
        self.plugin_name = name
        self._on_move = on_move

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(7)
        box.set_margin_bottom(7)
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

        if on_step:
            up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
            up_btn.add_css_class("flat")
            up_btn.set_valign(Gtk.Align.CENTER)
            up_btn.set_size_request(34, 34)
            up_btn.set_tooltip_text("Move up")
            up_btn.connect("clicked", lambda _: on_step(name, -1))
            box.append(up_btn)

            down_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
            down_btn.add_css_class("flat")
            down_btn.set_valign(Gtk.Align.CENTER)
            down_btn.set_size_request(34, 34)
            down_btn.set_tooltip_text("Move down")
            down_btn.connect("clicked", lambda _: on_step(name, 1))
            box.append(down_btn)

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
