#!/bin/bash
set -e

PROJECT_DIR="/mnt/d/HTML/CODE OS"
RELEASE_DIR="$PROJECT_DIR/release"
DEB_STAGING="/tmp/code-os-deb-staging"


echo "[1/5] Setting up deb staging directory at $DEB_STAGING..."
rm -rf "$DEB_STAGING"
mkdir -p "$DEB_STAGING/DEBIAN"
mkdir -p "$DEB_STAGING/opt/code-os"
mkdir -p "$DEB_STAGING/usr/bin"
mkdir -p "$DEB_STAGING/usr/share/applications"
mkdir -p "$DEB_STAGING/usr/share/icons/hicolor/512x512/apps"

echo "[2/5] Copying linux-unpacked files to /opt/code-os..."
cp -r "$RELEASE_DIR/linux-unpacked/"* "$DEB_STAGING/opt/code-os/"
chmod -R 755 "$DEB_STAGING/opt/code-os"

echo "[3/5] Installing icons and desktop entries..."
cp "$PROJECT_DIR/build/icon.png" "$DEB_STAGING/usr/share/icons/hicolor/512x512/apps/code-os.png"

cat << 'EOF' > "$DEB_STAGING/usr/share/applications/code-os.desktop"
[Desktop Entry]
Name=CODE OS
Comment=Local-first AI development workspace and IDE
Exec=/opt/code-os/code-os %U
Icon=code-os
Type=Application
StartupNotify=true
StartupWMClass=code-os
Categories=Development;IDE;TextEditor;
EOF
chmod 644 "$DEB_STAGING/usr/share/applications/code-os.desktop"

cat << 'EOF' > "$DEB_STAGING/usr/bin/code-os"
#!/bin/bash
exec /opt/code-os/code-os "$@"
EOF
chmod 755 "$DEB_STAGING/usr/bin/code-os"

echo "[4/5] Writing DEBIAN/control file..."
cat << 'EOF' > "$DEB_STAGING/DEBIAN/control"
Package: code-os
Version: 2.4.0
Section: devel
Priority: optional
Architecture: amd64
Maintainer: Roopesh Kosuri <roopesh@codeos.ai>
Depends: libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, libsecret-1-0
Homepage: https://github.com/Roopesh-kosuri/code-os
Description: CODE OS - Local-first AI developer operating system
 CODE OS is a local-first AI IDE that plans, codes, reviews, and runs
 software with strict server-side boundaries and multi-model failover.
EOF

echo "[5/5] Building .deb package with dpkg-deb..."
dpkg-deb --build --root-owner-group "$DEB_STAGING" "$RELEASE_DIR/code-os_2.4.0_amd64.deb"

echo "✓ Successfully built: $RELEASE_DIR/code-os_2.4.0_amd64.deb"
rm -rf "$DEB_STAGING"
