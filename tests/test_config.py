"""Tests for lsmm.core.config — Steam library detection and VDF parsing."""

from pathlib import Path

from lsmm.core.config import (
    _parse_library_paths,
    find_library_for_app,
    get_all_library_paths,
)


# ── VDF fixtures ──────────────────────────────────────────────────────────────

_VDF_TWO_LIBS = """\
"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"/home/user/.local/share/Steam"
\t\t"label"\t\t""
\t}
\t"1"
\t{
\t\t"path"\t\t"/mnt/games/SteamLibrary"
\t\t"label"\t\t"Games Drive"
\t}
}
"""

_VDF_DECK = """\
"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"/home/deck/.local/share/Steam"
\t}
\t"1"
\t{
\t\t"path"\t\t"/run/media/deck/SteamLibrary"
\t\t"label"\t\t"SD Card"
\t}
}
"""

_VDF_NO_PATHS = """\
"libraryfolders"
{
}
"""


# ── _parse_library_paths ──────────────────────────────────────────────────────

def test_parse_library_paths_multi_library(tmp_path):
    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text(_VDF_TWO_LIBS, encoding="utf-8")
    paths = _parse_library_paths(vdf)
    assert len(paths) == 2
    assert Path("/home/user/.local/share/Steam") in paths
    assert Path("/mnt/games/SteamLibrary") in paths


def test_parse_library_paths_missing_file(tmp_path):
    paths = _parse_library_paths(tmp_path / "nonexistent.vdf")
    assert paths == []


def test_parse_library_paths_no_entries(tmp_path):
    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text(_VDF_NO_PATHS, encoding="utf-8")
    assert _parse_library_paths(vdf) == []


def test_parse_library_paths_sd_card_path(tmp_path):
    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text(_VDF_DECK, encoding="utf-8")
    paths = _parse_library_paths(vdf)
    assert Path("/run/media/deck/SteamLibrary") in paths


def test_parse_library_paths_encoding_error(tmp_path):
    vdf = tmp_path / "libraryfolders.vdf"
    # Write bytes with invalid UTF-8 sequence embedded in otherwise valid VDF
    raw = b'"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"/home/user/Steam\xff\xfe"\n\t}\n}\n'
    vdf.write_bytes(raw)
    # Must not raise — returns whatever paths were parseable
    paths = _parse_library_paths(vdf)
    assert isinstance(paths, list)


# ── get_all_library_paths ─────────────────────────────────────────────────────

def test_get_all_library_paths_uses_steam_root(tmp_path, monkeypatch):
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    vdf = steamapps / "libraryfolders.vdf"
    vdf.write_text(_VDF_TWO_LIBS, encoding="utf-8")
    monkeypatch.setattr("lsmm.core.config.get_steam_root", lambda: tmp_path)
    paths = get_all_library_paths()
    assert len(paths) == 2


def test_get_all_library_paths_no_steam_root(monkeypatch):
    monkeypatch.setattr("lsmm.core.config.get_steam_root", lambda: None)
    assert get_all_library_paths() == []


# ── find_library_for_app ──────────────────────────────────────────────────────

def test_find_library_for_app_finds_nondefault(tmp_path, monkeypatch):
    lib1 = tmp_path / "lib1"
    lib2 = tmp_path / "lib2"
    (lib1 / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps" / "appmanifest_12345.acf").write_text("")

    vdf = tmp_path / "steamapps" / "libraryfolders.vdf"
    vdf.parent.mkdir(parents=True)
    vdf.write_text(
        f'"libraryfolders"\n{{\n'
        f'\t"0"\n\t{{\n\t\t"path"\t\t"{lib1}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{lib2}"\n\t}}\n'
        f'}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("lsmm.core.config.get_steam_root", lambda: tmp_path)
    result = find_library_for_app(12345)
    assert result == lib2


def test_find_library_for_app_fallback_to_root(tmp_path, monkeypatch):
    (tmp_path / "steamapps").mkdir()
    vdf = tmp_path / "steamapps" / "libraryfolders.vdf"
    vdf.write_text(_VDF_NO_PATHS, encoding="utf-8")
    monkeypatch.setattr("lsmm.core.config.get_steam_root", lambda: tmp_path)
    result = find_library_for_app(99999)
    assert result == tmp_path


def test_find_library_for_app_no_steam_root(monkeypatch):
    monkeypatch.setattr("lsmm.core.config.get_steam_root", lambda: None)
    assert find_library_for_app(12345) is None
