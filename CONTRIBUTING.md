# Contributing to Linux Steam ModManager

Thanks for your interest in contributing!

## Before you start

- **Open an issue first** for any non-trivial change so we can align on scope.
- For small bug fixes, a PR without a prior issue is fine.

## Development setup

```bash
git clone https://github.com/pyromeister/Linux-Steam-ModManager
cd Linux-Steam-ModManager

# System dependencies (Debian/Ubuntu)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 p7zip-full unrar

# Run the GUI
python3 modlauncher-gui.py
```

No pip dependencies — standard library only.

## Adding engine support for a new game

1. Create `games/yourgame.json` with `app_id`, `install_path`, and `script_extender` fields (see `games/starfield.json` as reference).
2. If the game uses a custom mod system, create `engines/yourgame.py` extending `BaseEngine` from `engines/base.py`.
3. Register the engine in `modlauncher.py` → `load_engine()` and `src/gui/app.py` → `load_engine()`.

## Pull request checklist

- [ ] Describe what changes and why in the PR body
- [ ] Reference any related issue (`Closes #N`)
- [ ] Tested manually against at least one game profile

## Code style

- Python 3.10+, no external pip dependencies
- Keep GUI code in `src/gui/`, engine logic in `engines/`, game data in `games/`
- Prefer small, focused commits

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml).
