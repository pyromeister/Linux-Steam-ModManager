"""Tests for lsmm.gui.handlers.install — FOMOD detection path (ISC-37/38/39)."""

from unittest.mock import MagicMock, patch

from lsmm.gui.handlers.install import _install_one


# ── fixtures ──────────────────────────────────────────────────────────────────

def _window():
    win = MagicMock()
    win._toast = MagicMock()
    return win


def _engine():
    eng = MagicMock()
    eng.install = MagicMock()
    return eng


# ── ISC-39: non-FOMOD archive installs without fomod_files ────────────────────

def test_non_fomod_archive_installs_normally(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    engine = _engine()
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=None):
        _install_one(_window(), path, engine)
    engine.install.assert_called_once_with(path, fomod_files=None, staging=True)


# ── ISC-37: detect_fomod called before engine.install ─────────────────────────

def test_detect_fomod_called_for_every_archive(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    engine = _engine()
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=None) as mock_detect:
        _install_one(_window(), path, engine)
    mock_detect.assert_called_once_with(path)


# ── ISC-37/38: FOMOD config triggers ask_fomod, result passed to install ──────

def test_fomod_config_passed_to_engine_install(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    fake_config = MagicMock()
    fake_files = [("Low/s.ini", "s.ini")]
    engine = _engine()
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=fake_config), \
         patch("lsmm.gui.handlers.install.ask_fomod", return_value=fake_files):
        _install_one(_window(), path, engine)
    engine.install.assert_called_once_with(path, fomod_files=fake_files, staging=True)


# ── ISC-38: cancelled FOMOD (None) skips engine.install ──────────────────────

def test_fomod_cancel_skips_install(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    fake_config = MagicMock()
    engine = _engine()
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=fake_config), \
         patch("lsmm.gui.handlers.install.ask_fomod", return_value=None):
        _install_one(_window(), path, engine)
    engine.install.assert_not_called()
