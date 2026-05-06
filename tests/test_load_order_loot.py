"""Tests for LOOT sort button in load order handler (ISC-13..19, no GTK)."""

import threading
from unittest.mock import MagicMock, patch, call

from lsmm.gui.handlers.load_order import do_sort_with_loot


# ── helpers ───────────────────────────────────────────────────────────────────

def _window(loot_available=True, has_load_order=True):
    win = MagicMock()
    win.engine = MagicMock()
    win.engine.has_load_order = has_load_order
    win.engine.profile = {"slug": "skyrim_se", "name": "Skyrim Special Edition"}
    from types import SimpleNamespace
    win.engine.paths = SimpleNamespace(game_root=MagicMock())
    win._toast = MagicMock()
    win._refresh_load_order = MagicMock()
    return win


# ── ISC-16: sort runs in background thread ────────────────────────────────────

def test_sort_runs_in_background_thread():
    main_thread = threading.current_thread()
    sort_thread = []

    def fake_sort(profile, game_root):
        sort_thread.append(threading.current_thread())

    win = _window()
    with patch("lsmm.gui.handlers.load_order.sort_with_loot", side_effect=fake_sort), \
         patch("lsmm.gui.handlers.load_order._glib") as mock_glib:
        mock_glib.return_value.idle_add = lambda fn, *a: fn(*a)
        do_sort_with_loot(win)

    import time; time.sleep(0.05)
    assert sort_thread and sort_thread[0] is not main_thread


# ── ISC-17: load order refreshes after successful sort ────────────────────────

def test_load_order_refreshes_after_sort():
    win = _window()
    event = threading.Event()

    def fake_sort(profile, game_root):
        pass

    def fake_idle_add(fn, *a):
        fn(*a)
        event.set()

    with patch("lsmm.gui.handlers.load_order.sort_with_loot", side_effect=fake_sort), \
         patch("lsmm.gui.handlers.load_order._glib") as mock_glib:
        mock_glib.return_value.idle_add = fake_idle_add
        do_sort_with_loot(win)
        event.wait(timeout=2)

    win._refresh_load_order.assert_called()


# ── ISC-18: sort failure shows toast ─────────────────────────────────────────

def test_sort_failure_shows_toast():
    win = _window()
    event = threading.Event()

    def fake_sort(profile, game_root):
        raise RuntimeError("LOOT not found")

    def fake_idle_add(fn, *a):
        fn(*a)
        event.set()

    with patch("lsmm.gui.handlers.load_order.sort_with_loot", side_effect=fake_sort), \
         patch("lsmm.gui.handlers.load_order._glib") as mock_glib:
        mock_glib.return_value.idle_add = fake_idle_add
        do_sort_with_loot(win)
        event.wait(timeout=2)

    win._toast.assert_called()
    assert "LOOT" in win._toast.call_args[0][0] or "LOOT" in str(win._toast.call_args)


# ── ISC-18: refresh NOT called on failure ────────────────────────────────────

def test_load_order_not_refreshed_on_sort_failure():
    win = _window()
    event = threading.Event()

    def fake_sort(profile, game_root):
        raise RuntimeError("LOOT not found")

    def fake_idle_add(fn, *a):
        fn(*a)
        event.set()

    with patch("lsmm.gui.handlers.load_order.sort_with_loot", side_effect=fake_sort), \
         patch("lsmm.gui.handlers.load_order._glib") as mock_glib:
        mock_glib.return_value.idle_add = fake_idle_add
        do_sort_with_loot(win)
        event.wait(timeout=2)

    win._refresh_load_order.assert_not_called()
