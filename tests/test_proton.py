"""Tests for lsmm.core.proton — Proton detection and launch command building."""

from unittest.mock import patch

from lsmm.core.proton import (
    _parse_compat_tool_name,
    _resolve_proton_dir,
    find_proton_for_game,
    build_proton_launch_cmd,
)


_CONFIG_VDF = """\
"InstallConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"CompatToolMapping"
\t\t\t\t{
\t\t\t\t\t"22380"
\t\t\t\t\t{
\t\t\t\t\t\t"name"\t\t"Proton 9.0"
\t\t\t\t\t\t"config"\t\t""
\t\t\t\t\t\t"Priority"\t\t"250"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
"""


# ── _parse_compat_tool_name ───────────────────────────────────────────────────

def test_parse_compat_tool_name_found(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.vdf").write_text(_CONFIG_VDF)
    assert _parse_compat_tool_name(tmp_path, "22380") == "Proton 9.0"


def test_parse_compat_tool_name_missing(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.vdf").write_text(_CONFIG_VDF)
    assert _parse_compat_tool_name(tmp_path, "99999") is None


# ── _resolve_proton_dir ───────────────────────────────────────────────────────

def test_resolve_proton_dir_steamapps(tmp_path):
    proton = tmp_path / "steamapps/common/Proton 9.0/proton"
    proton.parent.mkdir(parents=True)
    proton.touch()
    with patch("lsmm.core.proton.get_all_library_paths", return_value=[tmp_path]):
        result = _resolve_proton_dir(tmp_path, "Proton 9.0")
    assert result == proton


def test_resolve_proton_dir_compattools(tmp_path):
    proton = tmp_path / "compatibilitytools.d/GE-Proton9-27/proton"
    proton.parent.mkdir(parents=True)
    proton.touch()
    with patch("lsmm.core.proton.get_all_library_paths", return_value=[]):
        result = _resolve_proton_dir(tmp_path, "GE-Proton9-27")
    assert result == proton


def test_resolve_proton_dir_not_found(tmp_path):
    with patch("lsmm.core.proton.get_all_library_paths", return_value=[]):
        assert _resolve_proton_dir(tmp_path, "Proton 99.0") is None


# ── find_proton_for_game ──────────────────────────────────────────────────────

def test_find_proton_for_game_full(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.vdf").write_text(_CONFIG_VDF)
    proton = tmp_path / "steamapps/common/Proton 9.0/proton"
    proton.parent.mkdir(parents=True)
    proton.touch()
    with patch("lsmm.core.proton.get_all_library_paths", return_value=[tmp_path]):
        result = find_proton_for_game(tmp_path, "22380")
    assert result == proton


def test_find_proton_for_game_no_tool_name(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/config.vdf").write_text(_CONFIG_VDF)
    assert find_proton_for_game(tmp_path, "99999") is None


# ── build_proton_launch_cmd ───────────────────────────────────────────────────

def test_build_proton_cmd_native(tmp_path):
    proton = tmp_path / "proton"
    loader = tmp_path / "nvse_loader.exe"
    steam_root = tmp_path / "Steam"
    compat_data = tmp_path / "compatdata/22380"
    with patch("lsmm.core.proton._in_flatpak", return_value=False):
        cmd, env = build_proton_launch_cmd(proton, loader, "22380", steam_root, compat_data)
    assert cmd == [str(proton), "waitforexitandrun", str(loader)]
    assert env["STEAM_APP_ID"] == "22380"
    assert env["STEAM_COMPAT_DATA_PATH"] == str(compat_data)
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == str(steam_root)


def test_build_proton_cmd_flatpak(tmp_path):
    proton = tmp_path / "proton"
    loader = tmp_path / "nvse_loader.exe"
    steam_root = tmp_path / "Steam"
    compat_data = tmp_path / "compatdata/22380"
    with patch("lsmm.core.proton._in_flatpak", return_value=True):
        cmd, env = build_proton_launch_cmd(proton, loader, "22380", steam_root, compat_data)
    assert cmd[0] == "flatpak-spawn"
    assert cmd[1] == "--host"
    assert any("STEAM_APP_ID=22380" in arg for arg in cmd)
    assert str(proton) in cmd
    assert env == {}
