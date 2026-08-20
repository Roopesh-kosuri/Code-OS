#!/bin/bash
set -e

PROJECT_DIR="/mnt/d/HTML/CODE OS"
RELEASE_DIR="$PROJECT_DIR/release"
APPDIR="/tmp/code-os-appimage"

echo "[1/4] Preparing AppDir at $APPDIR..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"

echo "[2/4] Copying linux-unpacked files..."
cp -r "$RELEASE_DIR/linux-unpacked/"* "$APPDIR/"
cp "$PROJECT_DIR/build/icon.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/code-os.png"
cp "$PROJECT_DIR/build/icon.png" "$APPDIR/code-os.png"

cat << 'EOF' > "$APPDIR/code-os.desktop"
[Desktop Entry]
Name=CODE OS
Comment=Local-first AI development workspace and IDE
Exec=code-os %U
Icon=code-os
Type=Application
StartupNotify=true
StartupWMClass=code-os
Categories=Development;IDE;TextEditor;
EOF

cat << 'EOF' > "$APPDIR/AppRun"
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/code-os" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "[3/4] Fetching appimagetool..."
if [ ! -s /tmp/appimagetool ]; then
  curl -sSfL -o /tmp/appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x /tmp/appimagetool
fi


echo "[4/4] Generating $RELEASE_DIR/CODE-OS-2.4.0.AppImage..."
ARCH=x86_64 /tmp/appimagetool --appimage-extract-and-run "$APPDIR" "$RELEASE_DIR/CODE-OS-2.4.0.AppImage"

echo "✓ Successfully built: $RELEASE_DIR/CODE-OS-2.4.0.AppImage"
rm -rf "$APPDIR"
