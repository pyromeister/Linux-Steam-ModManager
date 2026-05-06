"""Tests for lsmm.core.loot — LOOT detection and sort invocation."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from lsmm.core.loot import detect_loot, loot_game_id, sort_with_loot


# ── detect_loot ───────────────────────────────────────────────────────────────

def test_detect_loot_returns_native_when_on_path():
    with patch("lsmm.core.loot.shutil.which", return_value="/usr/bin/loot"):
        result = detect_loot()
    assert result == ["loot"]


def test_detect_loot_returns_flatpak_when_only_flatpak_installed():
    def which_side_effect(cmd):
        return "/usr/bin/flatpak" if cmd == "flatpak" else None

    with patch("lsmm.core.loot.shutil.which", side_effect=which_side_effect), \
         patch("lsmm.core.loot.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = detect_loot()

    assert result == ["flatpak", "run", "io.github.loot.loot"]


def test_detect_loot_returns_none_when_neither_available():
    with patch("lsmm.core.loot.shutil.which", return_value=None):
        result = detect_loot()
    assert result is None


def test_detect_loot_skips_flatpak_check_when_native_found():
    with patch("lsmm.core.loot.shutil.which", return_value="/usr/bin/loot"), \
         patch("lsmm.core.loot.subprocess.run") as mock_run:
        detect_loot()
    mock_run.assert_not_called()


# ── loot_game_id ──────────────────────────────────────────────────────────────

def test_loot_game_id_skyrim_se():
    assert loot_game_id({"slug": "skyrim_se"}) == "Skyrim Special Edition"


def test_loot_game_id_fallout4():
    assert loot_game_id({"slug": "fallout4"}) == "Fallout4"


def test_loot_game_id_starfield():
    assert loot_game_id({"slug": "starfield"}) == "Starfield"


def test_loot_game_id_returns_none_for_unknown_slug():
    assert loot_game_id({"slug": "planet_crafter"}) is None


# ── sort_with_loot ────────────────────────────────────────────────────────────

def test_sort_with_loot_raises_when_loot_not_detected(tmp_path):
    with patch("lsmm.core.loot.detect_loot", return_value=None):
        try:
            sort_with_loot({"slug": "skyrim_se"}, tmp_path)
            assert False, "Expected RuntimeError"
        except RuntimeError:
            pass


def test_sort_with_loot_raises_when_game_not_in_mapping(tmp_path):
    with patch("lsmm.core.loot.detect_loot", return_value=["loot"]):
        try:
            sort_with_loot({"slug": "planet_crafter"}, tmp_path)
            assert False, "Expected RuntimeError"
        except RuntimeError:
            pass


def test_sort_with_loot_invokes_correct_command(tmp_path):
    with patch("lsmm.core.loot.detect_loot", return_value=["loot"]), \
         patch("lsmm.core.loot.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        sort_with_loot({"slug": "skyrim_se"}, tmp_path)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "loot"
    assert "--game" in cmd
    assert cmd[cmd.index("--game") + 1] == "Skyrim Special Edition"
    assert "--game-path" in cmd
    assert cmd[cmd.index("--game-path") + 1] == str(tmp_path)
    assert "--auto-sort" in cmd


def test_sort_with_loot_propagates_nonzero_exit(tmp_path):
    with patch("lsmm.core.loot.detect_loot", return_value=["loot"]), \
         patch("lsmm.core.loot.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "loot")
        try:
            sort_with_loot({"slug": "skyrim_se"}, tmp_path)
            assert False, "Expected CalledProcessError"
        except subprocess.CalledProcessError:
            pass


def test_sort_with_loot_flatpak_command_prefix(tmp_path):
    flatpak_cmd = ["flatpak", "run", "io.github.loot.loot"]
    with patch("lsmm.core.loot.detect_loot", return_value=flatpak_cmd), \
         patch("lsmm.core.loot.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        sort_with_loot({"slug": "fallout4"}, tmp_path)

    cmd = mock_run.call_args[0][0]
    assert cmd[:3] == flatpak_cmd
    assert "--game" in cmd
    assert cmd[cmd.index("--game") + 1] == "Fallout4"
