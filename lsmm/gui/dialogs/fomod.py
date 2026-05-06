"""FOMOD installer dialog.

show_fomod_dialog(win, config, callback) — presents a multi-step modal dialog
that walks the user through FOMOD install choices.
callback(files) on Finish, callback(None) on Cancel.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from lsmm.core.fomod import FomodConfig, FomodGroup


# ── Pure logic ────────────────────────────────────────────────────────────────

def collect_fomod_files(
    config: FomodConfig,
    selections: list[list[set[str]]],
) -> list[tuple[str, str]]:
    """Build flat (src, dst) list from required files + selected plugin files.

    selections[step_idx][group_idx] = set of selected plugin names.
    Deduplicates; preserves insertion order.
    """
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []

    for pair in config.required_files:
        if pair not in seen:
            seen.add(pair)
            result.append(pair)

    for step_idx, step in enumerate(config.steps):
        if step_idx >= len(selections):
            continue
        for group_idx, group in enumerate(step.groups):
            if group_idx >= len(selections[step_idx]):
                continue
            selected = selections[step_idx][group_idx]
            for plugin in group.plugins:
                if plugin.name in selected:
                    for pair in plugin.files:
                        if pair not in seen:
                            seen.add(pair)
                            result.append(pair)

    return result


# ── Dialog ────────────────────────────────────────────────────────────────────

def show_fomod_dialog(win, config: FomodConfig, callback) -> None:
    """Present the FOMOD installer dialog modal over win.

    callback receives list[tuple[str,str]] on Finish or None on Cancel.
    """
    if not config.steps:
        callback(list(config.required_files))
        return
    dialog = _FomodDialog(win, config, callback)
    dialog.present()


class _FomodDialog(Adw.Window):
    def __init__(self, win, config: FomodConfig, callback):
        super().__init__(transient_for=win, modal=True, title=config.name)
        self.set_default_size(540, 460)
        self._config = config
        self._callback = callback
        self._step = 0
        self._selections: list[list[set[str]]] = _init_selections(config)
        self._build_ui()
        self._render_step()

    # ── UI structure ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._header = Adw.HeaderBar()
        self._header.set_show_end_title_buttons(False)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self._on_cancel())
        self._header.pack_start(cancel_btn)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_vexpand(True)
        self._scroll.set_hscrollbar_policy(Gtk.PolicyType.NEVER)

        self._back_btn = Gtk.Button(label="Back")
        self._back_btn.connect("clicked", lambda _: self._on_back())

        self._next_btn = Gtk.Button(label="Next")
        self._next_btn.add_css_class("suggested-action")
        self._next_btn.connect("clicked", lambda _: self._on_next())

        btn_row = Gtk.Box(spacing=8)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_start(16)
        btn_row.set_margin_end(16)
        btn_row.set_margin_top(8)
        btn_row.set_margin_bottom(12)
        btn_row.append(self._back_btn)
        btn_row.append(self._next_btn)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self._header)
        toolbar_view.set_content(self._scroll)
        toolbar_view.add_bottom_bar(btn_row)
        self.set_content(toolbar_view)

    # ── Step rendering ────────────────────────────────────────────────────────

    def _render_step(self) -> None:
        step = self._config.steps[self._step]
        is_last = self._step == len(self._config.steps) - 1

        self._next_btn.set_label("Finish" if is_last else "Next")
        self._back_btn.set_sensitive(self._step > 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)

        # Step heading (ISC-28)
        heading = Gtk.Label(label=f"<b>{step.name}</b>")
        heading.set_use_markup(True)
        heading.set_halign(Gtk.Align.START)
        outer.append(heading)

        for group_idx, group in enumerate(step.groups):
            outer.append(self._build_group(group, group_idx))

        self._scroll.set_child(outer)
        self._update_next_sensitivity()

    def _build_group(self, group: FomodGroup, group_idx: int) -> Gtk.Widget:
        pref_group = Adw.PreferencesGroup(title=group.name)
        sel = self._selections[self._step][group_idx]

        if group.type == "SelectExactlyOne":
            self._build_radio_group(pref_group, group, group_idx, sel)
        else:
            self._build_checkbox_group(pref_group, group, group_idx, sel)

        return pref_group

    def _build_radio_group(self, pref_group, group: FomodGroup, group_idx: int,
                           sel: set[str]) -> None:
        first_radio: Gtk.CheckButton | None = None
        for plugin in group.plugins:
            row = Adw.ActionRow(title=plugin.name, subtitle=plugin.description)
            radio = Gtk.CheckButton()
            radio.set_valign(Gtk.Align.CENTER)

            if first_radio is None:
                first_radio = radio
            else:
                radio.set_group(first_radio)

            sensitive = plugin.type_descriptor not in ("NotUsable",)
            radio.set_sensitive(sensitive)
            radio.set_active(plugin.name in sel)

            if plugin.type_descriptor == "Required":
                radio.set_active(True)
                radio.set_sensitive(False)

            plugin_name = plugin.name

            def on_toggled(btn, pn=plugin_name, gidx=group_idx):
                if btn.get_active():
                    self._selections[self._step][gidx] = {pn}
                    self._update_next_sensitivity()

            radio.connect("toggled", on_toggled)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)
            pref_group.add(row)

    def _build_checkbox_group(self, pref_group, group: FomodGroup, group_idx: int,
                              sel: set[str]) -> None:
        for plugin in group.plugins:
            row = Adw.ActionRow(title=plugin.name, subtitle=plugin.description)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)

            is_all = group.type == "SelectAll"
            is_required = plugin.type_descriptor == "Required"
            is_not_usable = plugin.type_descriptor == "NotUsable"

            check.set_active(plugin.name in sel or is_all or is_required)
            check.set_sensitive(not is_all and not is_required and not is_not_usable)

            plugin_name = plugin.name

            def on_toggled(btn, pn=plugin_name, gidx=group_idx):
                s = self._selections[self._step][gidx]
                if btn.get_active():
                    s.add(pn)
                else:
                    s.discard(pn)
                self._update_next_sensitivity()

            check.connect("toggled", on_toggled)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            pref_group.add(row)

    # ── Sensitivity ───────────────────────────────────────────────────────────

    def _update_next_sensitivity(self) -> None:
        step = self._config.steps[self._step]
        for group_idx, group in enumerate(step.groups):
            if group.type == "SelectExactlyOne":
                if not self._selections[self._step][group_idx]:
                    self._next_btn.set_sensitive(False)
                    return
        self._next_btn.set_sensitive(True)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        self._callback(None)
        self.close()

    def _on_back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._render_step()

    def _on_next(self) -> None:
        if self._step < len(self._config.steps) - 1:
            self._step += 1
            self._render_step()
        else:
            files = collect_fomod_files(self._config, self._selections)
            self._callback(files)
            self.close()


# ── Selection initialisation ─────────────────────────────────────────────────

def _init_selections(config: FomodConfig) -> list[list[set[str]]]:
    """Pre-select plugins based on typeDescriptor and group type."""
    result = []
    for step in config.steps:
        step_sel = []
        for group in step.groups:
            sel: set[str] = set()
            for plugin in group.plugins:
                if plugin.type_descriptor == "Required":
                    sel.add(plugin.name)
                elif group.type == "SelectAll":
                    sel.add(plugin.name)
                elif plugin.type_descriptor == "Recommended":
                    if group.type == "SelectExactlyOne" and not sel:
                        sel.add(plugin.name)
                    elif group.type != "SelectExactlyOne":
                        sel.add(plugin.name)
            step_sel.append(sel)
        result.append(step_sel)
    return result
