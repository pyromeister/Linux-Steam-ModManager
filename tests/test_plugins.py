from lsmm.core.plugins import PluginsFile, PluginEntry


class TestPluginsFileRead:
    def test_reads_active_plugin(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        p.write_text("*ActiveMod.esm\n", encoding="utf-8")
        pf = PluginsFile.read(p)
        assert pf.plugins[0].name == "ActiveMod.esm"
        assert pf.plugins[0].active is True

    def test_reads_inactive_plugin(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        p.write_text("InactiveMod.esm\n", encoding="utf-8")
        pf = PluginsFile.read(p)
        assert pf.plugins[0].name == "InactiveMod.esm"
        assert pf.plugins[0].active is False

    def test_preserves_comment_lines(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        p.write_text("# This is a comment\n*Active.esm\n", encoding="utf-8")
        pf = PluginsFile.read(p)
        assert pf._lines[0] == "# This is a comment"
        assert len(pf.plugins) == 1

    def test_preserves_blank_lines(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        p.write_text("\n*Active.esm\n", encoding="utf-8")
        pf = PluginsFile.read(p)
        assert pf._lines[0] == ""

    def test_nonexistent_file_returns_empty(self, tmp_path):
        pf = PluginsFile.read(tmp_path / "nonexistent.txt")
        assert pf.plugins == []
        assert pf._lines == []

    def test_mixed_content_order_preserved(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        p.write_text("# header\n*A.esm\nB.esp\n# comment\n*C.esp\n", encoding="utf-8")
        pf = PluginsFile.read(p)
        assert len(pf.plugins) == 3
        assert pf.plugins[0].name == "A.esm"
        assert pf.plugins[1].name == "B.esp"
        assert pf.plugins[2].name == "C.esp"


class TestPluginsFileWrite:
    def test_round_trip_preserves_exact_content(self, tmp_path):
        content = "# Comment\n*Active.esm\nInactive.esm\n"
        p = tmp_path / "Plugins.txt"
        p.write_text(content, encoding="utf-8")
        pf = PluginsFile.read(p)
        pf.write()
        assert p.read_text(encoding="utf-8") == content

    def test_active_plugin_written_with_star(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        pf = PluginsFile(path=p, _lines=[PluginEntry(name="Mod.esm", active=True)])
        pf.write()
        assert p.read_text(encoding="utf-8") == "*Mod.esm\n"

    def test_inactive_plugin_written_without_star(self, tmp_path):
        p = tmp_path / "Plugins.txt"
        pf = PluginsFile(path=p, _lines=[PluginEntry(name="Mod.esm", active=False)])
        pf.write()
        assert p.read_text(encoding="utf-8") == "Mod.esm\n"


class TestPluginsFileAdd:
    def test_add_new_plugin_default_active(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[])
        pf.add("New.esm")
        entry = pf.get("New.esm")
        assert entry is not None
        assert entry.active is True

    def test_add_inactive_plugin(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[])
        pf.add("New.esm", active=False)
        assert pf.get("New.esm").active is False

    def test_add_does_not_duplicate(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[])
        pf.add("Mod.esm")
        pf.add("Mod.esm")
        assert len(pf.plugins) == 1

    def test_get_returns_none_for_missing(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[])
        assert pf.get("NotHere.esm") is None


class TestPluginsFileRemove:
    def test_remove_existing_plugin(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[PluginEntry("Mod.esm", True)])
        pf.remove("Mod.esm")
        assert pf.get("Mod.esm") is None

    def test_remove_preserves_other_plugins(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[
            PluginEntry("A.esm", True), PluginEntry("B.esp", False)
        ])
        pf.remove("A.esm")
        assert pf.get("B.esp") is not None

    def test_remove_nonexistent_is_no_op(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[])
        pf.remove("NoMod.esm")


class TestPluginsFileSetActive:
    def test_set_active_true(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[PluginEntry("Mod.esm", False)])
        pf.set_active("Mod.esm", True)
        assert pf.get("Mod.esm").active is True

    def test_set_active_false(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[PluginEntry("Mod.esm", True)])
        pf.set_active("Mod.esm", False)
        assert pf.get("Mod.esm").active is False

    def test_set_active_nonexistent_is_no_op(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[])
        pf.set_active("Ghost.esm", True)


class TestPluginsFileOrder:
    def test_get_order_returns_only_active(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[
            PluginEntry("A.esm", True), PluginEntry("B.esp", False)
        ])
        assert pf.get_order() == ["A.esm"]

    def test_get_full_order_returns_all(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[
            PluginEntry("A.esm", True), PluginEntry("B.esp", False)
        ])
        assert pf.get_full_order() == ["A.esm", "B.esp"]

    def test_set_order_reorders_plugins(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[
            PluginEntry("A.esm", True), PluginEntry("B.esp", True)
        ])
        pf.set_order(["B.esp", "A.esm"])
        assert pf.get_order() == ["B.esp", "A.esm"]

    def test_set_order_appends_unlisted_plugins(self, tmp_path):
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[
            PluginEntry("A.esm", True), PluginEntry("B.esp", False)
        ])
        pf.set_order(["A.esm"])
        assert "B.esp" in pf.get_full_order()

    def test_set_order_preserves_comment_lines(self, tmp_path):
        comment = "# header"
        pf = PluginsFile(path=tmp_path / "p.txt", _lines=[
            comment, PluginEntry("A.esm", True), PluginEntry("B.esp", False)
        ])
        pf.set_order(["B.esp", "A.esm"])
        assert comment in pf._lines


class TestPluginEntryStr:
    def test_active_entry_str_has_star(self):
        assert str(PluginEntry("Mod.esm", True)) == "*Mod.esm"

    def test_inactive_entry_str_no_star(self):
        assert str(PluginEntry("Mod.esm", False)) == "Mod.esm"
