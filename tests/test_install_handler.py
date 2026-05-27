"""Tests for lsmm.gui.handlers.install — FOMOD detection path (ISC-37/38/39)."""

from unittest.mock import MagicMock, patch

from lsmm.gui.handlers.install import _install_one


# ── fixtures ──────────────────────────────────────────────────────────────────

def _window():
    win = MagicMock()
    win._toast = MagicMock()
    return win


def _engine(supports_staging: bool = True):
    eng = MagicMock()
    eng.install = MagicMock()
    eng.supports_staging = supports_staging
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

def test_engine_without_staging_receives_no_staging_kwarg(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    engine = _engine(supports_staging=False)
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=None):
        _install_one(_window(), path, engine)
    engine.install.assert_called_once_with(path, fomod_files=None)


def test_engine_without_staging_force_install_receives_no_staging_kwarg(tmp_path):
    from lsmm.core.installer import ConflictError
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    engine = _engine(supports_staging=False)
    engine.install.side_effect = [ConflictError([("file.esp", "OtherMod")]), None]
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=None), \
         patch("lsmm.gui.handlers.install.ask_conflict", return_value=True):
        _install_one(_window(), path, engine)
    assert engine.install.call_count == 2
    engine.install.assert_called_with(path, force=True, fomod_files=None)


def test_fomod_cancel_skips_install(tmp_path):
    path = tmp_path / "mod.zip"
    path.write_bytes(b"fake")
    fake_config = MagicMock()
    engine = _engine()
    with patch("lsmm.gui.handlers.install.detect_fomod", return_value=fake_config), \
         patch("lsmm.gui.handlers.install.ask_fomod", return_value=None):
        _install_one(_window(), path, engine)
    engine.install.assert_not_called()
