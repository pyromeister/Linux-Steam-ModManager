# Linux Mod Manager

A native Linux mod manager for Steam games with engine-plugin architecture.
Supports Bethesda games (Starfield, Skyrim SE, Fallout 4) out of the box, with a
plugin system designed to support other games (RimWorld, Witcher 3, etc.) in the future.

> ⚠️ **Work in Progress — not yet usable.** Core architecture is in place but the project is in early development. Expect breaking changes, missing features, and bugs. Not recommended for actual use yet.

> **Note:** This project was built with [Claude Code](https://claude.ai/code) by Anthropic.
> The code was generated through an AI-assisted development session and is maintained by the repository owner.

---

## Why?

Mod managers on Linux are an afterthought. Mod Organizer 2 and Vortex run via Wine/Proton
but aren't native tools. Linux gaming is growing — the Steam Hardware Survey shows a steady
increase, and the Steam Deck has brought thousands of new Linux users. This project aims to
fill that gap with a proper native tool.

---

## Features

- Install mods from `.zip`, `.7z`, and `.rar` archives
- Automatically detects mod structure and copies files to the correct location
- Manages `Plugins.txt` load order for Bethesda games
- Enable / disable individual mods
- Reorder load order from the CLI
- Tracks installed files for clean uninstall (no leftover files)
- **Linux case-sensitivity fix:** normalizes directory names (`interface/` → `Interface/`, `sfse/plugins/` → `SFSE/Plugins/`) that Windows-packed mods get wrong
- Script extender launch setup (SFSE, SKSE, F4SE) via Proton wrapper
- Multi-game support via JSON game profiles

---

## Requirements

- Python 3.10+
- `unzip` — for `.zip` archives
- `p7zip` — for `.7z` archives (`sudo apt install p7zip-full`)
- `unrar` — for `.rar` archives (`sudo apt install unrar`)
- Steam with Proton (for Bethesda games)

---

## Installation

```bash
git clone https://github.com/yourusername/linux-mod-manager
cd linux-mod-manager
```

No pip dependencies — standard library only.

---

## Usage

```bash
# List installed mods and current load order
python3 modlauncher.py --game starfield list

# Install a mod from an archive
python3 modlauncher.py --game starfield install ~/Downloads/SomeMod.zip

# Install with a custom name
python3 modlauncher.py --game starfield install ~/Downloads/SomeMod.zip MyModName

# Uninstall a mod (removes all tracked files)
python3 modlauncher.py --game starfield uninstall MyModName

# Enable / disable a mod
python3 modlauncher.py --game starfield enable MyModName
python3 modlauncher.py --game starfield disable MyModName

# Show and reorder load order
python3 modlauncher.py --game starfield order
python3 modlauncher.py --game starfield order MyMod.esm 2

# Set up the script extender launch wrapper (run once)
python3 modlauncher.py --game starfield setup-se

# Verify all paths are correct
python3 modlauncher.py --game starfield check

# List all supported games
python3 modlauncher.py games
```

---

## Supported Games

| Profile | Game | Engine | Script Extender |
|---------|------|--------|-----------------|
| `starfield` | Starfield | Bethesda | SFSE |
| `skyrim_se` | Skyrim Special Edition | Bethesda | SKSE |
| `fallout4` *(planned)* | Fallout 4 | Bethesda | F4SE |
| `rimworld` *(planned)* | RimWorld | RimWorld | — |
| `witcher3` *(planned)* | The Witcher 3 | Witcher3 | — |

---

## Project Structure

```
linux-mod-manager/
├── modlauncher.py       # CLI entry point
├── engines/
│   ├── base.py          # Abstract BaseEngine with capability flags
│   └── bethesda.py      # Bethesda engine (Starfield, Skyrim, Fallout)
├── games/
│   ├── starfield.json   # Game profile
│   └── skyrim_se.json
└── src/
    ├── config.py        # Path resolver from game profile
    ├── installer.py     # Archive extraction, structure detection, manifest
    └── plugins.py       # Plugins.txt read/write/reorder
```

### Adding a new game

1. Create `games/yourgame.json` with the game's Steam App ID, install path, and script extender info
2. If the game uses a different mod system, create `engines/yourgame.py` extending `BaseEngine`
3. Register the engine name in `modlauncher.py`'s `load_engine()`

---

## How the Bethesda engine works on Linux

Bethesda games run via Proton. Launching the script extender (SFSE/SKSE) requires a small
wrapper script — you can't just put the `.exe` path in Steam's launch options because Steam
will try to run it natively instead of through Proton.

`setup-se` generates this script automatically:

```bash
#!/bin/bash
exec "${@/Starfield.exe/sfse_loader.exe}"
```

Set Steam launch options to: `"/path/to/se_launch.sh" %command%`

---

## Contributing

Contributions welcome — especially engine plugins for new games.
Open an issue before starting large changes.

---

## License

MIT
