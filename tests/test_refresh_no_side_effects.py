"""Tests for #81: _refresh_* methods must be read-only — no install/write side effects."""

import threading
from unittest.mock import MagicMock, patch

import pytest


class _SyncThread:
    """Replaces threading.Thread to run the target synchronously in tests."""
    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _make_win(version_prefix="Installed"):
    win = MagicMock()
    win.engine.has_framework_setup = True
    win.engine.framework_name = "BepInEx"
    win.engine.profile = {"bepinex": {"github_repo": "BepInEx/BepInEx"}}
    win.engine.is_framework_installed.return_value = True
    win.engine.paths = None
    win._game_slug = "planet_crafter"
    win.games = [("planet_crafter", "Planet Crafter")]
    win._se_version_cache = {}
    win._se_check_in_flight = set()
    return win


@pytest.mark.gui
def test_refresh_framework_untracked_version_does_not_auto_install():
    """When framework is installed but version not in manifest,
    refresh must NOT call setup_framework — just show update available."""
    from lsmm.gui.handlers.mod_engine import refresh_mod_engine_tab

    win = _make_win()

    with patch("lsmm.core.installer.load_manifest", return_value={}), \
         patch("lsmm.gui.handlers.mod_engine.fetch_github_latest_tag", return_value="5.4.23"), \
         patch("lsmm.gui.handlers.mod_engine.GLib") as mock_glib, \
         patch("lsmm.gui.handlers.mod_engine.threading.Thread", _SyncThread):
        mock_glib.idle_add = MagicMock()
        refresh_mod_engine_tab(win)

    win.engine.setup_framework.assert_not_called()
    assert "5.4.23" in win._se_version_cache.get("planet_crafter", "")


@pytest.mark.gui
def test_refresh_framework_known_version_shows_up_to_date():
    """When installed version matches latest, refresh shows 'up to date' — no install."""
    from lsmm.gui.handlers.mod_engine import refresh_mod_engine_tab

    win = _make_win()
    manifest = {"BepInEx": {"nexus": {"version": "5.4.23"}}}

    with patch("lsmm.core.installer.load_manifest", return_value=manifest), \
         patch("lsmm.gui.handlers.mod_engine.fetch_github_latest_tag", return_value="5.4.23"), \
         patch("lsmm.gui.handlers.mod_engine.GLib") as mock_glib, \
         patch("lsmm.gui.handlers.mod_engine.threading.Thread", _SyncThread):
        mock_glib.idle_add = MagicMock()
        refresh_mod_engine_tab(win)

    win.engine.setup_framework.assert_not_called()
    assert "up to date" in win._se_version_cache.get("planet_crafter", "")


@pytest.mark.gui
def test_refresh_framework_no_github_release_does_not_install():
    """When GitHub returns no release info, refresh must NOT install."""
    from lsmm.gui.handlers.mod_engine import refresh_mod_engine_tab

    win = _make_win()

    with patch("lsmm.core.installer.load_manifest", return_value={}), \
         patch("lsmm.gui.handlers.mod_engine.fetch_github_latest_tag", return_value=None), \
         patch("lsmm.gui.handlers.mod_engine.GLib") as mock_glib, \
         patch("lsmm.gui.handlers.mod_engine.threading.Thread", _SyncThread):
        mock_glib.idle_add = MagicMock()
        refresh_mod_engine_tab(win)

    win.engine.setup_framework.assert_not_called()
