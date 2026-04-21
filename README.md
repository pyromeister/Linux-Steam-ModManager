# Linux Steam ModManager (LSMM)

<p align="center">
  <img src="assets/icon.png" width="128" alt="LSMM Logo"/>
</p>

A native Linux mod manager for Steam games with engine-plugin architecture.
Supports Bethesda games (Starfield, Skyrim SE, Fallout 4) out of the box, with a
plugin system designed to support other games (RimWorld, Witcher 3, etc.) in the future.

> ⚠️ **Early Alpha.** Core features work (Starfield tested). Expect rough edges. Not recommended for large mod setups yet.

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
- **NXM URL import** *(experimental)* — paste an `nxm://` link from Nexus Mods for direct download + install (requires free Nexus API key)
- **Update check** — "Check Updates" button queries Nexus Mods API for newer versions of installed mods (NXM-imported only; requires API key)
- **Progress bar** — install and download operations show a progress bar; NXM downloads display real percentage, file installs use pulse mode
- **Games panel** — dedicated left column lists all game profiles; click to switch game, import external profiles via "Add", remove profiles via "Remove"
- **Mod profiles** — save and restore named loadouts (active mods + load order) per game
- Automatically detects mod structure and copies files to the correct location
- Handles standard `Data/`, double-nested `Data/Data/`, single-wrapper `ModName/Data/`, and bare-root layouts
- Manages `Plugins.txt` load order for Bethesda games
- Enable / disable individual mods
- Reorder load order via drag & drop in the GUI
- **Archive cache:** each mod archive is copied to `~/.local/share/linux-mod-manager/archives/{game}/` on install — the original can be moved or deleted without affecting the tracked state
- **Backup before overwrite:** if a mod install would overwrite an existing file (vanilla or from another mod), the original is backed up to `~/.local/share/linux-mod-manager/backups/{game}/{mod}/` and restored automatically on uninstall
- Tracks installed files for clean uninstall (no leftover files)
- **Linux case-sensitivity fix:** normalizes directory names (`interface/` → `Interface/`, `sfse/plugins/` → `SFSE/Plugins/`) that Windows-packed mods get wrong
- Script extender launch setup (SFSE, SKSE, F4SE) via Proton wrapper
- Multi-game support via JSON game profiles

---

## Requirements

- Python 3.10+
- GTK 4 + libadwaita (for the GUI): `sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`
- `p7zip-full` — for `.7z` archives: `sudo apt install p7zip-full`
- `unrar` — for `.rar` archives: `sudo apt install unrar`
- `.zip` archives are handled by Python's standard library (no extra tool needed)
- Steam with Proton (for Bethesda games)

---

## Usage — GUI

```bash
python3 modlauncher-gui.py
```

Select your game from the dropdown. The load order panel appears automatically
for games that support it (Bethesda games). Use **+ Install** to open a file
chooser — you can select multiple archives at once and they will be installed
sequentially.

---

## Installation

```bash
git clone https://github.com/pyromeister/Linux-Steam-ModManager
cd Linux-Steam-ModManager
```

No pip dependencies — standard library only (GUI requires system GTK4 packages, see Requirements).

---

## Usage — CLI

```bash
# List installed mods and current load order
python3 modlauncher.py --game starfield list

# Install a mod from an archive
python3 modlauncher.py --game starfield install ~/Downloads/SomeMod.zip

# Install with a custom name
python3 modlauncher.py --game starfield install ~/Downloads/SomeMod.zip MyModName

# Uninstall a mod (removes all tracked files, restores any backups)
python3 modlauncher.py --game starfield uninstall MyModName

# Enable / disable a mod
python3 modlauncher.py --game starfield enable MyModName
python3 modlauncher.py --game starfield disable MyModName

# Show load order
python3 modlauncher.py --game starfield order

# Set up the script extender launch wrapper (run once)
python3 modlauncher.py --game starfield setup-se

# Verify all paths are correct
python3 modlauncher.py --game starfield check

# List all supported games
python3 modlauncher.py games
```

---

## Managed directories

The manager keeps its data under `~/.local/share/linux-mod-manager/`:

```
~/.local/share/linux-mod-manager/
├── archives/
│   └── starfield/          ← cached copy of every installed archive
│       ├── SomeMod.zip
│       └── AnotherMod.7z
└── backups/
    └── starfield/
        └── SomeMod/        ← files overwritten by SomeMod, restored on uninstall
            └── Data/
                └── Interface/
                    └── somefile.swf
```

---

## Supported Games

| Profile | Game | Engine | Script Extender |
|---------|------|--------|-----------------|
| `starfield` | Starfield | Bethesda | SFSE |
| `skyrim_se` | Skyrim Special Edition | Bethesda | SKSE |
| `planet_crafter` | The Planet Crafter | BepInEx | BepInEx *(auto-installed via "Install BepInEx" button)* |
| `fallout4` *(planned)* | Fallout 4 | Bethesda | F4SE |
| `rimworld` *(planned)* | RimWorld | RimWorld | — |
| `witcher3` *(planned)* | The Witcher 3 | Witcher3 | — |

---

## Project Structure

```
linux-mod-manager/
├── modlauncher.py       # CLI entry point
├── modlauncher-gui.py   # GUI entry point (GTK4 + libadwaita)
├── engines/
│   ├── base.py          # Abstract BaseEngine with capability flags
│   └── bethesda.py      # Bethesda engine (Starfield, Skyrim, Fallout)
├── games/
│   ├── starfield.json   # Game profile
│   └── skyrim_se.json
└── src/
    ├── config.py        # Path resolver, Steam detection, managed dir constants
    ├── installer.py     # Archive extraction, structure detection, manifest, cache, backups
    ├── plugins.py       # Plugins.txt read/write/reorder
    └── gui/
        └── app.py       # GTK4 window, mod list, load order panel
```

### Adding a new game

1. Create `games/yourgame.json` with the game's Steam App ID, install path, and script extender info
2. If the game uses a different mod system, create `engines/yourgame.py` extending `BaseEngine`
3. Register the engine name in `modlauncher.py`'s `load_engine()` and in `src/gui/app.py`'s `load_engine()`

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
