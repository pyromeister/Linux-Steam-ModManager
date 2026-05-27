# QA and test strategy

This project should not require a real desktop or Steam Deck for every change.
Use a layered test strategy instead:

1. Fast automated checks on every PR
2. Heavier automated checks when needed
3. Manual desktop/Steam Deck QA before releases

## Test layers

### 1. Fast PR checks

Run these for every pull request and every push to `main`:

```bash
flake8 . --count --max-line-length=120 --exclude=__pycache__,.git
pytest -m "not gui and not integration and not network and not manual" -q
pytest --cov=lsmm --cov-report=term-missing --cov-fail-under=21 tests/
```

The coverage threshold is intentionally low for now because the repository
currently has broad GUI and engine code with limited automated coverage. Raise
`--cov-fail-under` gradually as new tests land. This is a coverage ratchet: it
should trend upward, not block all work immediately.

### 2. GUI smoke tests without a real client

Most GUI import and startup regressions can be tested headlessly with Xvfb.
This is suitable for GitHub Actions, a VM, or an LXC that has GTK/libadwaita
packages installed.

Debian/Ubuntu packages:

```bash
sudo apt-get update
sudo apt-get install -y \
  dbus-x11 \
  gir1.2-adw-1 \
  gir1.2-gtk-4.0 \
  libadwaita-1-0 \
  libgtk-4-1 \
  python3-gi \
  python3-gi-cairo \
  python3-pip \
  python3-venv \
  xvfb
```

Use a virtual environment that can see the system GTK bindings:

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
dbus-run-session -- xvfb-run -a pytest -m gui tests/gui -q
```

Why `--system-site-packages`? PyGObject depends on system GObject/GTK
libraries. Installing `python3-gi` via apt and then using a normal isolated venv
usually hides those bindings from Python.

### 3. Handler/controller tests

Prefer moving business logic out of GTK widget methods and into handlers or
controllers. Those tests should not require GTK or a display.

Good targets:

- `lsmm/gui/handlers/install.py`
- `lsmm/gui/handlers/mod_engine.py`
- `lsmm/gui/handlers/games.py`
- `lsmm/gui/handlers/profiles.py`

Use fake engines, fake windows, temp directories, and monkeypatching instead of
real Steam libraries or real network calls.

### 4. Integration and security tests

Mark slower or more environment-sensitive tests explicitly:

```python
import pytest

pytestmark = pytest.mark.integration
```

Available markers:

- `gui`: requires GTK/libadwaita and usually Xvfb
- `integration`: slower multi-subsystem tests
- `network`: requires external network access
- `manual`: not run automatically

Run all non-manual tests:

```bash
pytest -m "not manual"
```

Run GUI tests only:

```bash
pytest -m gui tests/gui -q
```

## What still needs a real client or Steam Deck?

Use a real Linux desktop or Steam Deck for release QA, not for every commit.
Headless tests catch crashes and logic regressions, but they do not prove that
the application feels good to use.

Manual desktop QA checklist:

- [ ] `lsmm-gui` starts from a terminal
- [ ] First-run flow works
- [ ] Settings dialog opens and saves changes
- [ ] Steam library/game detection works
- [ ] A game can be selected
- [ ] A mod can be installed
- [ ] A mod can be uninstalled
- [ ] FOMOD dialog works for a representative archive
- [ ] Conflict dialog works
- [ ] Error details are visible when an operation fails
- [ ] Logs can be exported
- [ ] NXM URL handling works in the desktop environment

Manual Steam Deck QA checklist:

- [ ] App starts in Desktop Mode
- [ ] Window size and scaling are usable
- [ ] Touch input is usable
- [ ] Controller focus/navigation is acceptable where applicable
- [ ] Dialogs are not clipped
- [ ] Steam library paths are detected correctly
- [ ] Proton-related paths/actions work for a representative game

## Recommended workflow for fixes

For bugs and behavior changes, use test-first development:

1. Add a failing regression test that reproduces the bug.
2. Run the specific test and verify it fails for the expected reason.
3. Implement the smallest fix.
4. Run the specific test again and verify it passes.
5. Run the relevant suite (`pytest -q`, GUI tests, or integration tests).

This keeps the test suite useful instead of just documenting the current
implementation.
