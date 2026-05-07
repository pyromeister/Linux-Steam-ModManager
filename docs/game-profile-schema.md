# Game Profile Schema

Game profiles are JSON files that tell LSMM how to manage mods for a specific game.

Drop a file into `~/.config/linux-mod-manager/games/<slug>.json` to add a game or override a bundled profile without touching the installation.

## Required fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name shown in the UI |
| `steam_app_id` | string | Steam application ID |
| `engine` | string | Engine plugin — see [Engines](#engines) |
| `game_exe` | string | Game executable (e.g. `Starfield.exe`) |
| `install_subdir` | string | Folder name inside the Steam library (e.g. `Starfield`) |

## Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `nexus_domain` | string | Nexus Mods game domain (e.g. `starfield`) — enables NXM links |
| `mod_dir` | string | Subdirectory inside the game folder where mods land (default: `Data`) |
| `appdata_name` | string | Override AppData folder name for Plugins.txt (Bethesda only) |
| `script_extender` | object | See [Script extender](#script-extender) |

## Engines

| Value | Use for |
|-------|---------|
| `bethesda` | Starfield, Skyrim SE, Fallout 4 — manages Plugins.txt |
| `modfolder` | Stardew Valley (SMAPI), 7 Days to Die — copies files into mod folder |
| `bepinex` | Planet Crafter, Craftopia — Unity + BepInEx |
| `rimworld` | RimWorld — reads/writes ModsConfig.xml |

## Script extender

Only needed for `bethesda` games that have a script extender (SFSE, SKSE, F4SE).

```json
"script_extender": {
  "name": "SFSE",
  "loader_exe": "sfse_loader.exe",
  "plugins_dir": "Data/SFSE/Plugins"
}
```

## Example

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

The `<slug>` (filename without `.json`) becomes the internal identifier used with `--game` on the CLI.
