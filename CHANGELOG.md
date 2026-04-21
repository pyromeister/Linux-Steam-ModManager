# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0-alpha] - 2026-04-21

### Added
- GTK4 + libadwaita GUI (`modlauncher-gui.py`)
- CLI entry point (`modlauncher.py`)
- Bethesda engine — Starfield, Skyrim SE, Fallout 4
- BepInEx engine — Planet Crafter (auto-install via GUI button)
- RimWorld game profile (planned)
- NXM URL import — paste `nxm://` link for direct Nexus download (experimental)
- Nexus Mods update check via API key
- Mod profiles / loadouts per game (save, load, delete)
- Drag & drop load order reordering
- Archive cache (`~/.local/share/linux-mod-manager/archives/`)
- Backup before overwrite; auto-restore on uninstall
- Linux case-sensitivity fix for Windows-packed mod archives
- Script extender launch wrapper setup (SFSE, SKSE, F4SE)
- Progress bar for install and NXM download operations
- Games panel with profile switching, add, and remove
- App icon and dark mode (Adwaita)

[Unreleased]: https://github.com/pyromeister/Linux-Steam-ModManager/compare/v0.1.0-alpha...HEAD
[0.1.0-alpha]: https://github.com/pyromeister/Linux-Steam-ModManager/releases/tag/v0.1.0-alpha
