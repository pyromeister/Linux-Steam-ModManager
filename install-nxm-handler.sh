#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/linux-mod-manager.desktop"

mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Linux Steam ModManager
Exec=python3 $SCRIPT_DIR/src/gui/app.py %u
Type=Application
MimeType=x-scheme-handler/nxm;
NoDisplay=true
StartupNotify=false
EOF

xdg-mime default linux-mod-manager.desktop x-scheme-handler/nxm
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "✓ NXM handler registered."
echo "Note: restart your browser for the changes to take effect."
