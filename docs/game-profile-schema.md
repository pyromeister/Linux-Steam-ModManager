# Game Profile Schema

Game profiles are JSON files that tell LSMM how to manage mods for a specific game.

## Location

| Priority | Path |
|----------|------|
| 1 — user override | `~/.config/linux-mod-manager/games/<slug>.json` |
| 2 — bundled | installed package data under `lsmm/games/` |

Drop a file in the user directory to add a new game or override a bundled profile without modifying the installation. The `<slug>` is the filename without `.json` and is used with `--game`.

## Required fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name shown in the UI |
| `steam_app_id` | string | Steam application ID |
| `engine` | string | Engine plugin — see [Engines](#engines) |
| `game_exe` | string | Game executable filename |
| `install_subdir` | string | Folder name inside `steamapps/common/` |

## Common optional fields

| Field | Type | Description |
|-------|------|-------------|
| `nexus_domain` | string | Nexus Mods game domain; enables NXM links and update checks |
| `appdata_name` | string | AppData folder override for Bethesda `Plugins.txt` paths, e.g. `FalloutNV` |
| `proton` | boolean | Marks a profile as Proton/Windows-oriented for engine-specific behavior |
| `script_extender` | object/null | Bethesda script extender metadata; see below |
| `modfolder` | object | Required for `modfolder` engine profiles |
| `smapi` | object | Optional SMAPI auto-install metadata for Stardew Valley-style profiles |
| `bepinex` | object | Optional BepInEx install metadata |

## Engines

| Value | Use for |
|-------|---------|
| `bethesda` | Starfield, Skyrim SE, Fallout 4, Fallout: New Vegas — manages `Data/` and `Plugins.txt` |
| `modfolder` | Stardew Valley, 7 Days to Die — copies files into a dedicated mods folder |
| `bepinex` | The Planet Crafter, Craftopia — Unity + BepInEx |
| `rimworld` | RimWorld — manages RimWorld mod folders and `ModsConfig.xml` |

## Script extender

Only for `bethesda` games that have a script extender.

```json
"script_extender": {
  "name": "SFSE",
  "loader_exe": "sfse_loader.exe",
  "plugins_dir": "Data/SFSE/Plugins",
  "asset_prefix": "sfse_",
  "github_repo": "owner/repo"
}
```

Known fields:

| Field | Description |
|-------|-------------|
| `name` | Short name shown in the UI, e.g. `SFSE`, `SKSE`, `F4SE`, `NVSE` |
| `loader_exe` | Script extender loader executable inside the game root |
| `plugins_dir` | Path relative to the game root where SE plugin DLLs live |
| `github_repo` | GitHub releases repo used by update/install helpers when applicable |
| `github_tags_repo` | GitHub tags repo used when releases are not available |
| `asset_prefix` | Release/tag asset prefix used to identify the correct download |
| `download_page` | Fallback/manual download page shown to the user |

Set `"script_extender": null` or omit it if the game has no script extender.

## ModFolder options

Required when `"engine": "modfolder"`.

```json
"modfolder": {
  "mods_dir": "Mods"
}
```

| Field | Description |
|-------|-------------|
| `mods_dir` | Subdirectory inside the game folder where mods are placed |

## SMAPI options

Optional. When present, LSMM can install/update SMAPI from GitHub releases.

```json
"smapi": {
  "executable": "StardewModdingAPI",
  "launch_script": "unix-launcher.sh",
  "github_repo": "Pathoschild/SMAPI",
  "asset_name": "installer.zip",
  "installer_subdir": "internal/linux",
  "install_dat": "install.dat",
  "game_deps_file": "Stardew Valley.deps.json",
  "launch_env_prefix": "SMAPI_USE_CURRENT_SHELL=true"
}
```

## BepInEx options

Optional metadata used by the BepInEx engine.

```json
"bepinex": {
  "plugins_dir": "BepInEx/plugins",
  "build": "win_x64",
  "github_repo": "BepInEx/BepInEx"
}
```

| Field | Description |
|-------|-------------|
| `plugins_dir` | Plugins folder relative to the game root |
| `build` | BepInEx build flavor, e.g. `win_x64` |
| `github_repo` | GitHub repo used for BepInEx release lookup when available |

## Examples

### Bethesda game with script extender

```json
{
  "name": "Starfield",
  "steam_app_id": "1716740",
  "engine": "bethesda",
  "game_exe": "Starfield.exe",
  "install_subdir": "Starfield",
  "nexus_domain": "starfield",
  "script_extender": {
    "name": "SFSE",
    "loader_exe": "sfse_loader.exe",
    "plugins_dir": "Data/SFSE/Plugins",
    "asset_prefix": "sfse_",
    "github_tags_repo": "ianpatt/sfse",
    "download_page": "https://www.nexusmods.com/starfield/mods/106"
  }
}
```

### ModFolder game

```json
{
  "name": "7 Days to Die",
  "steam_app_id": "251570",
  "engine": "modfolder",
  "game_exe": "7DaysToDie.x86_64",
  "install_subdir": "7 Days To Die",
  "nexus_domain": "7daystodie",
  "modfolder": {
    "mods_dir": "Mods"
  }
}
```

### BepInEx game

```json
{
  "name": "The Planet Crafter",
  "steam_app_id": "1284190",
  "engine": "bepinex",
  "game_exe": "Planet Crafter.exe",
  "install_subdir": "The Planet Crafter",
  "nexus_domain": "theplanetcrafter",
  "proton": true,
  "bepinex": {
    "plugins_dir": "BepInEx/plugins",
    "build": "win_x64",
    "github_repo": "BepInEx/BepInEx"
  }
}
```
