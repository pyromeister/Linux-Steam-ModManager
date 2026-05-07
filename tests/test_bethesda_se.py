"""Tests for BethesdaEngine SE auto-download methods."""

import json
import stat
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lsmm.core import installer
from lsmm.engines.bethesda import BethesdaEngine

_PROFILE_SE = {
    "name": "Starfield",
    "slug": "starfield",
    "steam_app_id": "1716740",
    "install_subdir": "Starfield",
    "engine": "bethesda",
    "game_exe": "Starfield.exe",
    "script_extender": {
        "name": "SFSE",
        "loader_exe": "sfse_loader.exe",
        "plugins_dir": "Data/SFSE/Plugins",
        "github_repo": "ianpatt/sfse",
        "asset_prefix": "sfse_",
    },
}

_PROFILE_NO_REPO = {
    "name": "Fallout NV",
    "slug": "falloutnv",
    "steam_app_id": "22380",
    "install_subdir": "Fallout New Vegas",
    "engine": "bethesda",
    "game_exe": "FalloutNV.exe",
    "script_extender": {
        "name": "NVSE",
        "loader_exe": "nvse_loader.exe",
        "plugins_dir": "Data/NVSE/Plugins",
    },
}

_FAKE_RELEASE = {
    "tag_name": "0.2.38",
    "assets": [
        {"name": "sfse_0_2_38.7z", "browser_download_url": "https://example.com/sfse_0_2_38.7z"},
        {"name": "sfse_readme.txt", "browser_download_url": "https://example.com/sfse_readme.txt"},
    ],
}


@pytest.fixture()
def eng(tmp_path, monkeypatch):
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    plugins_txt = tmp_path / "Plugins.txt"
    plugins_txt.write_text("")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")

    monkeypatch.setattr(installer, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(installer, "ARCHIVES_DIR", tmp_path / "archives")
    monkeypatch.setattr(installer, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(installer, "_migration_done", True)

    engine = BethesdaEngine(_PROFILE_SE)
    engine.paths = SimpleNamespace(
        data_dir=data_dir,
        plugins_txt=plugins_txt,
        se_plugins_dir=None,
        game_root=tmp_path,
        se_loader=tmp_path / "sfse_loader.exe",
    )
    return engine


def _mock_urlopen(release_data: dict):
    """Return a context manager that yields a fake HTTP response with release JSON."""
    body = json.dumps(release_data).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = lambda s: resp
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ── get_se_latest_info ────────────────────────────────────────────────────────

def test_get_se_latest_info_returns_version_url_filename(eng):
    with patch("lsmm.engines.bethesda.urllib.request.urlopen", return_value=_mock_urlopen(_FAKE_RELEASE)):
        result = eng.get_se_latest_info()
    assert result is not None
    version, url, filename = result
    assert version == "0.2.38"
    assert "sfse_0_2_38.7z" in url
    assert filename == "sfse_0_2_38.7z"


def test_get_se_latest_info_returns_none_on_http_error(eng):
    import urllib.error
    with patch("lsmm.engines.bethesda.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(None, 404, "Not Found", {}, None)):
        result = eng.get_se_latest_info()
    assert result is None


def test_get_se_latest_info_returns_none_when_no_matching_asset(eng):
    release_no_match = {"tag_name": "0.2.38", "assets": [
        {"name": "changelog.txt", "browser_download_url": "https://example.com/changelog.txt"},
    ]}
    with patch("lsmm.engines.bethesda.urllib.request.urlopen",
               return_value=_mock_urlopen(release_no_match)):
        result = eng.get_se_latest_info()
    assert result is None


def test_get_se_latest_info_returns_none_when_no_github_repo(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")
    monkeypatch.setattr(installer, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(installer, "ARCHIVES_DIR", tmp_path / "archives")
    monkeypatch.setattr(installer, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(installer, "_migration_done", True)
    engine = BethesdaEngine(_PROFILE_NO_REPO)
    engine.paths = SimpleNamespace(
        data_dir=tmp_path / "Data",
        plugins_txt=tmp_path / "Plugins.txt",
        se_plugins_dir=None,
        game_root=tmp_path,
        se_loader=tmp_path / "nvse_loader.exe",
    )
    result = engine.get_se_latest_info()
    assert result is None


# ── download_script_extender ──────────────────────────────────────────────────

def _make_download_resp(content: bytes):
    """Fake urlopen response for a file download."""
    resp = MagicMock()
    resp.headers.get.return_value = str(len(content))
    chunks = [content[i:i+65536] for i in range(0, len(content), 65536)] + [b""]
    resp.read.side_effect = chunks
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    cm = MagicMock()
    cm.__enter__ = lambda s: resp
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_download_script_extender_extracts_zip(eng, tmp_path):
    # Build a fake zip in memory
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sfse_loader.exe", b"fake loader")
    zip_bytes = buf.getvalue()

    release_zip = {
        "tag_name": "0.2.38",
        "assets": [{"name": "sfse_0_2_38.zip", "browser_download_url": "https://example.com/sfse.zip"}],
    }

    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(release_zip)
        return _make_download_resp(zip_bytes)

    with patch("lsmm.engines.bethesda.urllib.request.urlopen", side_effect=fake_urlopen):
        eng.download_script_extender()

    assert (eng.paths.game_root / "sfse_loader.exe").exists()


def test_download_script_extender_raises_on_7z_failure(eng):
    release_7z = {
        "tag_name": "0.2.38",
        "assets": [{"name": "sfse_0_2_38.7z", "browser_download_url": "https://example.com/sfse.7z"}],
    }

    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(release_7z)
        return _make_download_resp(b"not a real 7z")

    bad_result = MagicMock(returncode=1, stderr=b"bad archive")
    with patch("lsmm.engines.bethesda.urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("lsmm.engines.bethesda.subprocess.run", return_value=bad_result):
        with pytest.raises(RuntimeError, match="7z extraction failed"):
            eng.download_script_extender()


def test_download_script_extender_calls_progress(eng, tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sfse_loader.exe", b"x")
    zip_bytes = buf.getvalue()

    release_zip = {
        "tag_name": "0.2.38",
        "assets": [{"name": "sfse_0.zip", "browser_download_url": "https://x.com/sfse.zip"}],
    }

    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_urlopen(release_zip)
        return _make_download_resp(zip_bytes)

    progress_calls = []
    with patch("lsmm.engines.bethesda.urllib.request.urlopen", side_effect=fake_urlopen):
        eng.download_script_extender(on_progress=lambda d, t: progress_calls.append((d, t)))

    assert len(progress_calls) > 0


# ── setup_script_extender ─────────────────────────────────────────────────────

def test_setup_script_extender_creates_launch_script(eng):
    script_path = eng.setup_script_extender()
    assert script_path.name == "se_launch.sh"
    assert script_path.exists()
    content = script_path.read_text()
    assert "sfse_loader.exe" in content
    assert "Starfield.exe" in content


def test_setup_script_extender_is_executable(eng):
    script_path = eng.setup_script_extender()
    mode = script_path.stat().st_mode
    assert mode & stat.S_IEXEC
