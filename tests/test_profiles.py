"""Tests for lsmm.core.profiles — active tracking, rename, dirty detection."""

import pytest
from lsmm.core import profiles as prof


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, "PROFILES_DIR", tmp_path)


# ── set_active / get_active ───────────────────────────────────────────────────

def test_get_active_returns_none_when_no_profile_ever_set():
    assert prof.get_active("skyrim_se") is None


def test_set_active_persists_name():
    prof.save("skyrim_se", "Vanilla", ["ModA"], [])
    prof.set_active("skyrim_se", "Vanilla")
    assert prof.get_active("skyrim_se") == "Vanilla"


def test_set_active_none_clears_active():
    prof.save("skyrim_se", "Vanilla", ["ModA"], [])
    prof.set_active("skyrim_se", "Vanilla")
    prof.set_active("skyrim_se", None)
    assert prof.get_active("skyrim_se") is None


def test_set_active_isolated_per_slug():
    prof.save("skyrim_se", "Vanilla", [], [])
    prof.save("starfield", "Vanilla", [], [])
    prof.set_active("skyrim_se", "Vanilla")
    assert prof.get_active("starfield") is None


# ── rename ────────────────────────────────────────────────────────────────────

def test_rename_changes_profile_name():
    prof.save("skyrim_se", "Old Name", ["ModA"], [])
    prof.rename("skyrim_se", "Old Name", "New Name")
    assert prof.get("skyrim_se", "New Name") is not None
    assert prof.get("skyrim_se", "Old Name") is None


def test_rename_updates_active_when_renamed_set_was_active():
    prof.save("skyrim_se", "Old Name", ["ModA"], [])
    prof.set_active("skyrim_se", "Old Name")
    prof.rename("skyrim_se", "Old Name", "New Name")
    assert prof.get_active("skyrim_se") == "New Name"


def test_rename_leaves_active_unchanged_when_other_set_active():
    prof.save("skyrim_se", "Alpha", [], [])
    prof.save("skyrim_se", "Beta", [], [])
    prof.set_active("skyrim_se", "Alpha")
    prof.rename("skyrim_se", "Beta", "Beta2")
    assert prof.get_active("skyrim_se") == "Alpha"


def test_rename_raises_when_old_name_not_found():
    with pytest.raises(ValueError, match="not found"):
        prof.rename("skyrim_se", "Ghost", "New")


def test_rename_raises_when_new_name_already_exists():
    prof.save("skyrim_se", "Alpha", [], [])
    prof.save("skyrim_se", "Beta", [], [])
    with pytest.raises(ValueError, match="already exists"):
        prof.rename("skyrim_se", "Alpha", "Beta")


# ── is_dirty ──────────────────────────────────────────────────────────────────

def test_is_dirty_false_when_mods_match_saved():
    prof.save("skyrim_se", "Vanilla", ["ModA", "ModB"], [])
    assert prof.is_dirty("skyrim_se", "Vanilla", ["ModA", "ModB"]) is False


def test_is_dirty_true_when_mod_added():
    prof.save("skyrim_se", "Vanilla", ["ModA"], [])
    assert prof.is_dirty("skyrim_se", "Vanilla", ["ModA", "ModB"]) is True


def test_is_dirty_true_when_mod_removed():
    prof.save("skyrim_se", "Vanilla", ["ModA", "ModB"], [])
    assert prof.is_dirty("skyrim_se", "Vanilla", ["ModA"]) is True


def test_is_dirty_false_order_insensitive():
    prof.save("skyrim_se", "Vanilla", ["ModA", "ModB"], [])
    assert prof.is_dirty("skyrim_se", "Vanilla", ["ModB", "ModA"]) is False


def test_is_dirty_false_when_profile_not_found():
    assert prof.is_dirty("skyrim_se", "Ghost", ["ModA"]) is False
