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

> ⚠️ **Alpha software.** Core install/manage flows work for several games, but expect rough edges. Keep backups before using LSMM with large or important mod setups.

---

## What it does

LSMM is a native GTK4/libadwaita mod manager that handles the mod lifecycle — archive install, enable/disable, load order, uninstall, backups, Nexus downloads, and profile management — without running the manager itself through Wine or Proton.

**Who it's for:** Steam Deck users and Linux gamers who want a native alternative to running Vortex or MO2 through Wine.

---

## Features

**Installation**
- Install from `.zip`, `.7z`, and `.rar` archives with automatic structure detection
- **NXM links** — click “Mod Manager Download” on Nexus Mods and let LSMM handle the download/install flow
- FOMOD installer support for complex multi-choice mods
- Conflict detection before install; backup + restore on uninstall
- Archive cache for installed mods

**Mod management**
- Enable/disable mods without uninstalling
- Drag-and-drop load order reordering where the engine supports it
- LOOT-assisted sorting for supported Bethesda games when LOOT is installed
- Search and alphabetic sort in the mod list
- Named mod profiles/loadouts per game
- Path overrides for game root, data directory, Proton prefix, and script-extender paths

**Nexus Mods integration**
- Requires a free [Nexus API key](https://www.nexusmods.com/users/myaccount?tab=api)
- NXM download handling with expiry/error feedback
- Collection import and collection update checks
- Mod update checks and “update all” flow
- Version and file size metadata in the mod list when available

**Linux / Steam Deck support**
- Native Steam, Flatpak Steam, and Snap Steam root detection
- Multi-library support including SD card libraries under `/run/media`
- First-run Steam path picker when auto-detection is ambiguous
- Linux case-sensitivity normalization for common Windows-packed mod folders
- Script extender detection/setup helpers for supported Bethesda games
- Self-update checks against GitHub releases, with snooze/disable options
- Rotating log file at `~/.local/state/linux-mod-manager/lsmm.log`

---

## Installation

**Option A — Flatpak** *(local build supported; Flathub release not published yet)*

See [`flatpak/README.md`](flatpak/README.md) for local Flatpak build/run instructions and NXM handler notes.

**Option B — from source**

1. Install system dependencies.

Ubuntu/Debian:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 p7zip-full
```

Fedora:

```bash
sudo dnf install python3-gobject gtk4 libadwaita p7zip p7zip-plugins
```

Arch:

```bash
sudo pacman -S python-gobject gtk4 libadwaita p7zip
```

2. Clone and install:

```bash
git clone https://github.com/pyromeister/Linux-Steam-ModManager.git
cd Linux-Steam-ModManager
pip install --user .
```

Requirements: Python 3.10+, GTK4, libadwaita 1.x, and 7-Zip/p7zip.

---

## Usage

Open the GUI:

```bash
lsmm-gui
```

Basic CLI examples:

```bash
lsmm games
lsmm --game starfield check
lsmm --game starfield install ~/Downloads/SomeMod.zip
lsmm --game starfield list
lsmm --game starfield order
lsmm --game starfield uninstall MyModName
```

Full command reference: [CLI Reference](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/CLI-Reference)

---

## Supported Games

Bundled profiles are generated from `lsmm/games/*.json`.

| Engine | Bundled games |
|--------|---------------|
| Bethesda | Starfield, Skyrim Special Edition, Fallout 4, Fallout: New Vegas |
| BepInEx | The Planet Crafter, Craftopia |
| ModFolder / SMAPI | Stardew Valley, 7 Days to Die |
| RimWorld | RimWorld |

[Full list with profile slugs, App IDs, and testing status →](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Supported-Games)

Want a game added? [Open a Game Request](https://github.com/pyromeister/Linux-Steam-ModManager/issues/new?template=game_request.yml)

---

## Custom Game Profiles

Add or override a game without modifying the installation by dropping a JSON profile into:

```text
~/.config/linux-mod-manager/games/<slug>.json
```

[Game Profile Schema →](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Game-Profile-Schema)

---

## Contributing

Contributions welcome, especially game profiles, engine plugins, testing, packaging, and Steam Deck QA.
Open an issue before starting large changes.

[Project Structure](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Project-Structure) · [Adding a New Game](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Adding-a-New-Game) · [Bethesda Engine Internals](https://github.com/pyromeister/Linux-Steam-ModManager/wiki/Bethesda-Engine-Internals)

---

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

> Built with [Claude Code](https://claude.ai/code).
