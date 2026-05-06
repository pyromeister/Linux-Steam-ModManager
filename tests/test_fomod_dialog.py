"""Tests for FOMOD dialog pure logic — no GTK display required."""

from lsmm.core.fomod import FomodConfig, FomodGroup, FomodPlugin, FomodStep
from lsmm.gui.dialogs.fomod import collect_fomod_files


# ── helpers ───────────────────────────────────────────────────────────────────

def _plugin(name, files, type_descriptor="Optional"):
    return FomodPlugin(name=name, description="", files=files,
                       type_descriptor=type_descriptor)


def _group(name, gtype, plugins):
    return FomodGroup(name=name, type=gtype, plugins=plugins)


def _step(name, groups):
    return FomodStep(name=name, groups=groups)


# ── collect_fomod_files ───────────────────────────────────────────────────────

class TestCollectFomodFiles:
    def test_empty_config_returns_empty_list(self):
        config = FomodConfig(name="X", required_files=[], steps=[])
        assert collect_fomod_files(config, []) == []

    def test_required_files_always_included(self):
        config = FomodConfig(
            name="X",
            required_files=[("core.esp", "core.esp")],
            steps=[],
        )
        result = collect_fomod_files(config, [])
        assert ("core.esp", "core.esp") in result

    def test_selected_plugin_files_included(self):
        plugin = _plugin("High", [("High/s.ini", "s.ini")])
        config = FomodConfig(
            name="X", required_files=[],
            steps=[_step("S", [_group("G", "SelectExactlyOne", [plugin])])],
        )
        assert ("High/s.ini", "s.ini") in collect_fomod_files(config, [[{"High"}]])

    def test_unselected_plugin_files_excluded(self):
        plugin = _plugin("High", [("High/s.ini", "s.ini")])
        config = FomodConfig(
            name="X", required_files=[],
            steps=[_step("S", [_group("G", "SelectExactlyOne", [plugin])])],
        )
        assert ("High/s.ini", "s.ini") not in collect_fomod_files(config, [[set()]])

    def test_required_files_not_duplicated_when_also_in_plugin(self):
        plugin = _plugin("Low", [("core.esp", "core.esp")])
        config = FomodConfig(
            name="X",
            required_files=[("core.esp", "core.esp")],
            steps=[_step("S", [_group("G", "SelectAny", [plugin])])],
        )
        result = collect_fomod_files(config, [[{"Low"}]])
        assert result.count(("core.esp", "core.esp")) == 1

    def test_multiple_steps_files_aggregated(self):
        p1 = _plugin("A", [("a.ini", "a.ini")])
        p2 = _plugin("B", [("b.dds", "b.dds")])
        config = FomodConfig(
            name="X", required_files=[],
            steps=[
                _step("S1", [_group("G1", "SelectExactlyOne", [p1])]),
                _step("S2", [_group("G2", "SelectExactlyOne", [p2])]),
            ],
        )
        result = collect_fomod_files(config, [[{"A"}], [{"B"}]])
        assert ("a.ini", "a.ini") in result
        assert ("b.dds", "b.dds") in result

    def test_multiple_groups_in_step_both_included(self):
        p1 = _plugin("X1", [("x1.ini", "x1.ini")])
        p2 = _plugin("X2", [("x2.ini", "x2.ini")])
        config = FomodConfig(
            name="X", required_files=[],
            steps=[_step("S", [
                _group("G1", "SelectAny", [p1]),
                _group("G2", "SelectAny", [p2]),
            ])],
        )
        result = collect_fomod_files(config, [[{"X1"}, {"X2"}]])
        assert ("x1.ini", "x1.ini") in result
        assert ("x2.ini", "x2.ini") in result

    def test_plugin_with_multiple_files(self):
        plugin = _plugin("Full", [("a.esp", "a.esp"), ("b.bsa", "b.bsa")])
        config = FomodConfig(
            name="X", required_files=[],
            steps=[_step("S", [_group("G", "SelectAny", [plugin])])],
        )
        result = collect_fomod_files(config, [[{"Full"}]])
        assert ("a.esp", "a.esp") in result
        assert ("b.bsa", "b.bsa") in result
