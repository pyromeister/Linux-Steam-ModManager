#!/usr/bin/env python3
"""
Linux Mod Manager — CLI
Usage:
  modlauncher.py --game starfield install <archive.zip>
  modlauncher.py --game starfield uninstall <mod_name>
  modlauncher.py --game starfield list
  modlauncher.py --game starfield enable <mod_name>
  modlauncher.py --game starfield disable <mod_name>
  modlauncher.py --game starfield order                   (show load order)
  modlauncher.py --game starfield order <mod> <position>  (move mod)
  modlauncher.py --game starfield setup-se                (script extender setup)
  modlauncher.py --game starfield setup-ini               (ini setup)
  modlauncher.py --game starfield check                   (verify paths)
  modlauncher.py games                                    (list available games)
"""

import json
import sys
import argparse
from pathlib import Path

# Bootstrap path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "engines"))

from config import load_profile, GAMES_DIR


def load_engine(game: str):
    profile = load_profile(game)
    engine_name = profile["engine"]

    if engine_name == "bethesda":
        from bethesda import BethesdaEngine
        return BethesdaEngine(profile)
    else:
        print(f"Engine '{engine_name}' not yet implemented.")
        sys.exit(1)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_install(engine, args):
    if not args.archive:
        print("Usage: install <path/to/archive>")
        sys.exit(1)
    archive = Path(args.archive)
    if not archive.exists():
        print(f"File not found: {archive}")
        sys.exit(1)
    engine.install(archive, args.name)


def cmd_uninstall(engine, args):
    if not args.mod_name:
        print("Usage: uninstall <mod_name>")
        sys.exit(1)
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
    if not args.mod_name:
        print("Usage: enable <mod_name>")
        sys.exit(1)
    engine.enable_mod(args.mod_name)


def cmd_disable(engine, args):
    if not args.mod_name:
        print("Usage: disable <mod_name>")
        sys.exit(1)
    engine.disable_mod(args.mod_name)


def cmd_order(engine, args):
    if not engine.has_load_order:
        print("This game's engine does not support load order.")
        return
    if args.mod_name and args.position is not None:
        engine.move_mod(args.mod_name, int(args.position))
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


def main():
    parser = argparse.ArgumentParser(description="Linux Mod Manager")
    parser.add_argument("--game", default="starfield", help="Game profile name")
    parser.add_argument("command", choices=list(COMMANDS.keys()))
    parser.add_argument("archive", nargs="?", help="Archive path (install)")
    parser.add_argument("mod_name", nargs="?", help="Mod name")
    parser.add_argument("name", nargs="?", help="Override mod name on install")
    parser.add_argument("position", nargs="?", help="Position for order command")

    args = parser.parse_args()

    if args.command == "games":
        cmd_games(None, args)
        return

    engine = load_engine(args.game)
    COMMANDS[args.command](engine, args)


if __name__ == "__main__":
    main()
