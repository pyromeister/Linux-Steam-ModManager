#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/linux-mod-manager.desktop"

mkdir -p "$DESKTOP_DIR"

# Prefer PATH, then ~/.local/bin (for non-login shells), then legacy shim
if command -v lsmm-gui &>/dev/null; then
    LSMM_GUI="lsmm-gui"
elif [ -x "$HOME/.local/bin/lsmm-gui" ]; then
    LSMM_GUI="$HOME/.local/bin/lsmm-gui"
else
    LSMM_GUI="python3 $SCRIPT_DIR/modlauncher-gui.py"
fi

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Linux Steam ModManager
Exec=$LSMM_GUI %u
Type=Application
MimeType=x-scheme-handler/nxm;
NoDisplay=false
StartupNotify=false
EOF

xdg-mime default linux-mod-manager.desktop x-scheme-handler/nxm
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# KDE Plasma: also register in plasma-mimeapps.list and rebuild service cache
PLASMA_MIME="$HOME/.config/plasma-mimeapps.list"
if ! grep -q "x-scheme-handler/nxm" "$PLASMA_MIME" 2>/dev/null; then
    python3 -c "
import configparser, os
path = os.path.expanduser('$PLASMA_MIME')
cfg = configparser.ConfigParser()
cfg.read(path)
if 'Default Applications' not in cfg:
    cfg['Default Applications'] = {}
cfg['Default Applications']['x-scheme-handler/nxm'] = 'linux-mod-manager.desktop'
with open(path, 'w') as f:
    cfg.write(f)
"
fi
for cmd in kbuildsycoca6 kbuildsycoca5; do
    if command -v "$cmd" &>/dev/null; then
        "$cmd" --noincremental 2>/dev/null || true
        break
    fi
done

echo "✓ NXM handler registered: $LSMM_GUI"
echo "Note: restart your browser for the changes to take effect."
