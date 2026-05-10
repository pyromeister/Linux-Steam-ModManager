from lsmm.gui.dialogs.update_results import _version_key, _filter_changelogs


class TestVersionKey:
    def test_numeric_ordering(self):
        assert _version_key("1.10") > _version_key("1.9")

    def test_equal_versions(self):
        assert _version_key("2.0") == _version_key("2.0")

    def test_major_ordering(self):
        assert _version_key("2.0") > _version_key("1.99")

    def test_mixed_string_parts(self):
        assert _version_key("1.0.alpha") < _version_key("1.0.beta")


class TestFilterChangelogs:
    def test_keeps_only_newer_versions(self):
        changelogs = {"1.0": "notes", "1.1": "notes", "1.2": "notes"}
        result = _filter_changelogs(changelogs, "1.1")
        assert "1.2" in result
        assert "1.1" not in result
        assert "1.0" not in result

    def test_returns_all_when_installed_version_empty(self):
        changelogs = {"1.0": "notes", "1.1": "notes"}
        result = _filter_changelogs(changelogs, "")
        assert result == changelogs

    def test_returns_all_when_installed_version_none(self):
        changelogs = {"1.0": "notes"}
        result = _filter_changelogs(changelogs, None)
        assert result == changelogs

    def test_returns_empty_when_already_latest(self):
        changelogs = {"1.0": "notes", "1.1": "notes"}
        result = _filter_changelogs(changelogs, "1.1")
        assert result == {}

    def test_handles_empty_changelogs(self):
        result = _filter_changelogs({}, "1.0")
        assert result == {}
