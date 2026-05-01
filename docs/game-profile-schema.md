# Game Profile Schema

Game profiles are JSON files that tell LSMM how to manage mods for a specific game.

## Location

| Priority | Path |
|----------|------|
| 1 (user, takes precedence) | `~/.config/linux-mod-manager/games/<slug>.json` |
| 2 (bundled) | installed alongside the package in `lsmm/games/` |

Drop a file in the user directory to add a new game or override a bundled profile.
The `<slug>` becomes the internal identifier (e.g. `oblivion`, `skyrim_se`).

## Required fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name shown in the UI |
| `steam_app_id` | string | Steam application ID (find at store.steampowered.com) |
| `engine` | string | Engine plugin — see [Engines](#engines) |
| `game_exe` | string | Game executable filename (e.g. `Starfield.exe`) |
| `install_subdir` | string | Subfolder name inside the Steam library (e.g. `Starfield`) |

## Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `nexus_domain` | string | Nexus Mods game domain (e.g. `starfield`) — enables NXM links |
| `mod_dir` | string | Subdirectory inside the game folder where mods are installed (default: `Data`) |
| `script_extender` | object | See [Script extender](#script-extender) |

## Engines

| Value | Games |
|-------|-------|
| `bethesda` | Starfield, Skyrim SE, Fallout 4 — manages `Plugins.txt` |
| `modfolder` | Stardew Valley (SMAPI), 7 Days to Die — copies files into mod folder |
| `bepinex` | Planet Crafter, Craftopia — Unity + BepInEx |
| `rimworld` | RimWorld — reads/writes `ModsConfig.xml` |

## Script extender

Only relevant for `bethesda` engine games that have a script extender.

```json
"script_extender": {
  "name": "SFSE",
  "loader_exe": "sfse_loader.exe",
  "plugins_dir": "Data/SFSE/Plugins"
}
```

## Full example

```json
{
  "name": "Oblivion Remastered",
  "steam_app_id": "2623190",
  "engine": "bethesda",
  "game_exe": "OblivionRemastered.exe",
  "install_subdir": "Oblivion Remastered",
  "nexus_domain": "oblivionremastered",
  "mod_dir": "OblivionRemastered/Content/Dev/ObvData/Data"
}
```
