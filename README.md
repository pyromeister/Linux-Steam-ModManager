# Linux Steam ModManager (LSMM)

<p align="center">
  <img src="assets/icon.png" width="96" alt="LSMM Logo"/>
</p>

<p align="center">
  Native Linux mod manager for Steam games — built for the Steam Deck.
</p>

<p align="center">
  <a href="#installation">Install</a> · <a href="#supported-games">Supported Games</a> · <a href="https://github.com/pyromeister/Linux-Steam-ModManager/wiki">Wiki</a> · <a href="https://github.com/pyromeister/Linux-Steam-ModManager/issues">Issues</a>
</p>

> ⚠️ **Early Alpha.** Core features work (Starfield tested). Not recommended for large mod setups yet.

---

## What it does

LSMM is a native GTK4 mod manager that handles the full mod lifecycle — download, install, enable/disable, uninstall — without Wine or Proton wrappers for the tool itself.

**Who it's for:** Steam Deck users and Linux gamers who want a real native mod manager instead of running Vortex or MO2 through Wine.

---

## Features

**Installation**
- Install from `.zip`, `.7z`, `.rar` archives — auto-detects mod structure
- **NXM links** — click "Mod Manager Download" on Nexus Mods, LSMM handles the rest
- FOMOD installer support for complex multi-choice mods
- Conflict detection before install; backup + restore on uninstall

**Mod management**
- Enable / disable mods without uninstalling
- Drag & drop load order reordering
- Search and alphabetic sort in the mod list
- Mod profiles — save and restore named loadouts per game

**Nexus Mods integration**
- Requires a free [Nexus API key](https://www.nexusmods.com/users/myaccount?tab=api)
- Import collections, check for updates, update all at once
- Version and file size shown in the mod list

**Under the hood**
- Multi-library support including SD card (`/run/media`)
- Linux case-sensitivity fix for Windows-packed archives
- Script extender detection (SFSE, SKSE, F4SE)
- LOOT load order sorting for Bethesda games

---

## Installation

**Option A — Flatpak** *(coming to Flathub — not yet released)*

**Option B — from source**

1. Install system dependencies (Ubuntu/Debian):

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 p7zip-full
```

2. Clone and install:

```bash
git clone https://github.com/pyromeister/Linux-Steam-ModManager.git
cd Linux-Steam-ModManager
pip install --user .
```

Requirements: Python 3.10+, GTK4, libadwaita 1.x, p7zip

---

## Usage

```bash
lsmm-gui          # open the GUI
```

```bash
lsmm --game starfield install ~/Downloads/SomeMod.zip
lsmm --game starfield list
lsmm --game starfield uninstall MyModName
```

Full command reference: [CLI Reference](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/CLI-Reference)

---

## Supported Games

| Engine | Games |
|--------|-------|
| Bethesda | Starfield, Skyrim SE, Fallout 4, Oblivion, Fallout NV, Fallout 3 |
| BepInEx | Planet Crafter, Craftopia |
| ModFolder / SMAPI | Stardew Valley (SMAPI auto-install), RimWorld, 7 Days to Die |

[Full list with details →](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Supported-Games)

Want a game added? [Open a Game Request](https://github.com/pyromeister/Linux-Steam-ModManager/issues/new?template=game_request.yml)

---

## Custom Game Profiles

Add any game without modifying the installation — drop a JSON file into `~/.config/linux-mod-manager/games/`.

[Game Profile Schema →](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Game-Profile-Schema)

---

## Contributing

Contributions welcome, especially engine plugins for new games.
Open an issue before starting large changes.

[Project Structure](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Project-Structure) · [Adding a New Game](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Adding-a-New-Game) · [Bethesda Engine Internals](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Bethesda-Engine-Internals)

---

## License

GPLv3 — see [LICENSE](LICENSE).

> Built with [Claude Code](https://claude.ai/code).
