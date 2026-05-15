#!/usr/bin/env python3
"""
Linux Steam ModManager — CLI
Usage:
  lsmm --game starfield install <archive.zip> [mod_name]
  lsmm --game starfield uninstall <mod_name>
  lsmm --game starfield list
  lsmm --game starfield enable <mod_name>
  lsmm --game starfield disable <mod_name>
  lsmm --game starfield order                   (show load order)
  lsmm --game starfield order <mod> <position>  (move mod)
  lsmm --game starfield setup-se                (script extender setup)
  lsmm --game starfield setup-ini               (ini setup)
  lsmm --game starfield check                   (verify paths)
  lsmm games                                    (list available games)
"""

import json
import logging
import sys
import argparse
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lsmm.core.config import load_profile, GAMES_DIR, LOG_PATH
from lsmm.engines import load_engine

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.DEBUG, handlers=[handler])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def _load_engine(game: str):
    profile = load_profile(game)
    profile["slug"] = game
    return load_engine(profile)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_install(engine, args):
    archive = Path(args.archive)
    if not archive.exists():
        print(f"File not found: {archive}")
        sys.exit(1)
    engine.install(archive, args.name)


def cmd_uninstall(engine, args):
    engine.uninstall(args.mod_name)


def cmd_list(engine, args):
    print(f"\n── Installed Mods ({engine.profile['name']}) ──")
    mods = engine.list_mods()
    if not mods:
        print("  (none)")
    else:
        for m in mods:
            status = "✓" if m["active"] else "✗"
            print(f"  [{status}] {m['name']}")

    if engine.has_load_order:
        print("\n── Load Order ──────────────────────────")
        for name in engine.get_load_order():
            print(f"  {name}")
    print()


def cmd_enable(engine, args):
    engine.enable_mod(args.mod_name)


def cmd_disable(engine, args):
    engine.disable_mod(args.mod_name)


def cmd_order(engine, args):
    if not engine.has_load_order:
        print("This game's engine does not support load order.")
        return
    if args.mod_name and args.position is not None:
        engine.move_mod(args.mod_name, args.position)
        print(f"✓ Moved '{args.mod_name}' to position {args.position}")
    else:
        order = engine.get_load_order()
        print("\n── Load Order ──────────────────────────")
        for i, name in enumerate(order):
            print(f"  {i:>3}. {name}")
        print()


def cmd_setup_se(engine, args):
    if not engine.has_script_extender:
        print("No script extender for this game.")
        return
    engine.setup_script_extender()


def cmd_setup_ini(engine, args):
    engine.ensure_ini()


def cmd_check(engine, args):
    warnings = engine.paths.verify()
    if warnings:
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("  ✓ All paths verified.")


def cmd_games(_engine, _args):
    print("\n── Available Games ─────────────────────")
    for p in sorted(GAMES_DIR.glob("*.json")):
        data = json.loads(p.read_text())
        print(f"  {p.stem:<20} {data['name']}")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {
    "install":   cmd_install,
    "uninstall": cmd_uninstall,
    "list":      cmd_list,
    "enable":    cmd_enable,
    "disable":   cmd_disable,
    "order":     cmd_order,
    "setup-se":  cmd_setup_se,
    "setup-ini": cmd_setup_ini,
    "check":     cmd_check,
    "games":     cmd_games,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lsmm",
        description="Linux Steam ModManager",
    )
    parser.add_argument(
        "--game", default="starfield", metavar="GAME",
        help="Game profile slug (default: starfield)",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # install
    p = sub.add_parser("install", help="Install a mod from an archive")
    p.add_argument("archive", help="Path to the archive file")
    p.add_argument("name", nargs="?", help="Override the mod name")

    # uninstall
    p = sub.add_parser("uninstall", help="Remove an installed mod")
    p.add_argument("mod_name", help="Mod name")

    # list
    sub.add_parser("list", help="List installed mods and load order")

    # enable
    p = sub.add_parser("enable", help="Enable a mod")
    p.add_argument("mod_name", help="Mod name")

    # disable
    p = sub.add_parser("disable", help="Disable a mod")
    p.add_argument("mod_name", help="Mod name")

    # order
    p = sub.add_parser("order", help="Show or change load order")
    p.add_argument("mod_name", nargs="?", help="Mod to move")
    p.add_argument("position", nargs="?", type=int, help="Target position (0-based)")

    # setup-se
    sub.add_parser("setup-se", help="Set up the script extender")

    # setup-ini
    sub.add_parser("setup-ini", help="Set up INI files")

    # check
    sub.add_parser("check", help="Verify installation paths")

    # games
    sub.add_parser("games", help="List available game profiles")

    return parser


def main():
    _setup_logging()
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "games":
        cmd_games(None, args)
        return

    engine = _load_engine(args.game)
    COMMANDS[args.command](engine, args)


if __name__ == "__main__":
    main()
