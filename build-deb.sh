#!/bin/bash
# build-deb.sh - Build Debian package with desktop integration
# Version: 1.1.1 (GUI wrapper included, PNG icon added)

set -euo pipefail

VERSION="1.1.1"
PACKAGE_NAME="network-recover"
MAINTAINER="Network Recovery Team <support@network-recover.com>"
DESCRIPTION="Production-Grade Linux Network Recovery Engine - Diagnose and repair network issues without reboot"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo "=============================================="
echo "  📦 Building Debian Package: $PACKAGE_NAME"
echo "  Version: $VERSION"
echo "=============================================="
echo ""

# Build directory
BUILD_DIR="./build-deb"
PKG_DIR="$BUILD_DIR/$PACKAGE_NAME-$VERSION"

# Clean old build
rm -rf "$BUILD_DIR"
mkdir -p "$PKG_DIR"

# Create directory structure
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/local/bin"
mkdir -p "$PKG_DIR/usr/local/lib/network-recover"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$PKG_DIR/usr/share/polkit-1/actions"
mkdir -p "$PKG_DIR/usr/share/doc/$PACKAGE_NAME"
mkdir -p "$PKG_DIR/var/log/network-events"
mkdir -p "$PKG_DIR/var/lib/network-recover/snapshots"

echo -e "${GREEN}✅ Directory structure created${NC}"

# Copy main script
cp src/network-recover "$PKG_DIR/usr/local/bin/"
chmod 755 "$PKG_DIR/usr/local/bin/network-recover"

# Copy GUI wrapper (NEW)
if [[ -f "src/network-recover-gui" ]]; then
    cp src/network-recover-gui "$PKG_DIR/usr/local/bin/"
    chmod 755 "$PKG_DIR/usr/local/bin/network-recover-gui"
    echo -e "${GREEN}✅ GUI wrapper copied${NC}"
else
    echo -e "${YELLOW}⚠️  src/network-recover-gui not found - skipping${NC}"
fi

# Copy modular components
cp -r diagnostics "$PKG_DIR/usr/local/lib/network-recover/"
cp -r repairs "$PKG_DIR/usr/local/lib/network-recover/"
cp -r collectors "$PKG_DIR/usr/local/lib/network-recover/"
chmod -R 755 "$PKG_DIR/usr/local/lib/network-recover/"

# Copy test script
cp tests/test-offline.sh "$PKG_DIR/usr/local/lib/network-recover/"
chmod 755 "$PKG_DIR/usr/local/lib/network-recover/test-offline.sh"

echo -e "${GREEN}✅ Files copied${NC}"

# Create scalable SVG icon (kept as before)
cat > "$PKG_DIR/usr/share/icons/hicolor/scalable/apps/network-recover.svg" << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">
  <defs>
    <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#2196F3;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#0D47A1;stop-opacity:1" />
    </linearGradient>
  </defs>
  <circle cx="24" cy="24" r="20" fill="url(#grad1)" opacity="0.9"/>
  <path d="M24 32 L24 28 M24 20 L24 16 M16 24 L20 24 M28 24 L32 24" stroke="white" stroke-width="2" stroke-linecap="round"/>
  <path d="M14 30 Q19 25 24 30" fill="none" stroke="white" stroke-width="2" stroke-linecap="round"/>
  <path d="M10 34 Q17 27 24 34" fill="none" stroke="white" stroke-width="2" stroke-linecap="round"/>
  <path d="M18 18 Q20 16 22 18" fill="none" stroke="white" stroke-width="1.5" stroke-linecap="round"/>
  <path d="M30 16 L34 12 L36 14 L32 18 L30 16Z" fill="#4CAF50" stroke="none"/>
  <circle cx="36" cy="36" r="6" fill="#FFC107" stroke="none" opacity="0.3"/>
  <path d="M36 32 L36 40 M32 36 L40 36" stroke="#FFC107" stroke-width="2" stroke-linecap="round" stroke-dasharray="2 2"/>
</svg>
EOF

# Create 48x48 PNG icon (NEW - base64 encoded minimal icon)
cat > "$PKG_DIR/usr/share/icons/hicolor/48x48/apps/network-recover.png" << 'EOF'
iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAAsQAAALEBxi1JjQAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAH7SURBVHic7ZqxTgJBEEXfXJHI/2/j/wgdGhqIhR0l0Qo7LU1qQ4IJ1gvJhZ7nZzazl72XJCFJhWEhF09Y+uP3+Hp/zg+zxeNzdZjaFpLUK9lw1WjrO++0/U/y2LkjBQ/4x7dcEMs9kAT7PZDWUEhChSSVhiBJpSEEJCkloQgESZqRUARiSJJKQxAkKaUhCESQpEISiiBJhSREIEiNJBQhCFK0NBIBCJKn0dIICIRpNBRBkNyNhiIIkrnRUEQgSFJ7o6GIQZCkQhKKIEjdhpYUQRCgQUuKIAiSoSVFEARJ35IiCAIkbUmKIAiQsiVFEATI1JIiCAKgbkmRhAAMrCieAABDAgCoVxRPAIAtAYBRUzwBADYEAEZN8QQAWBMA2BIAgC0BAGBLAKCQeAIArAkAFBJPALCVWMNjmNq6Uk1sO4n1KmkR81XSLGK+StpKghHwVdJWEoyAr5K2kmAEfJW0lQQj4KukrSQYAV8lbSXBCPgqaSsJRsBXSZNJMAK+SpKEMQK+SpKEMQK+SpKEMQK+SlJJGAHvqyQVhRHwqkpaFUbAqyrJKowAD1VJq8II8FAlrQojwIuStCqMAA+S1BBGwIUkNYQRcC5JDWEEfJOkhjACLknSgjACLklSQxgBpySpIYyAM5L0RBgB3yTpShgBdyRpThgBdyRpTRgBr0jShDACnkiSE0bAE0mSE0bAU0mywgg4IklHqCk18gl7atdckq4kqVpSkqQkSVL/AaCrvLgX1RlZAAAAAElFTkSuQmCC
EOF

echo -e "${GREEN}✅ Icons created${NC}"

# Copy desktop file from the desktop/ directory (instead of generating)
if [[ -f "desktop/network-recover.desktop" ]]; then
    cp desktop/network-recover.desktop "$PKG_DIR/usr/share/applications/"
    chmod 644 "$PKG_DIR/usr/share/applications/network-recover.desktop"
    echo -e "${GREEN}✅ Desktop entry copied (points to GUI wrapper)${NC}"
else
    echo -e "${YELLOW}⚠️  desktop/network-recover.desktop not found - creating fallback${NC}"
    cat > "$PKG_DIR/usr/share/applications/network-recover.desktop" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Network Diagnose & Repair
Comment=Diagnose and fix network connectivity issues
Exec=pkexec /usr/local/bin/network-recover-gui
Icon=network-recover
Terminal=false
Categories=System;Network;
StartupNotify=true
X-XFCE-Settings=Network
EOF
    chmod 644 "$PKG_DIR/usr/share/applications/network-recover.desktop"
fi

# Create polkit policy (unchanged)
cat > "$PKG_DIR/usr/share/polkit-1/actions/com.network-recover.policy" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="com.network-recover.diagnose">
    <description>Run network diagnostics and repair</description>
    <message>Authentication is required to diagnose and repair network connectivity</message>
    <icon_name>network-recover</icon_name>
    <defaults>
      <allow_any>no</allow_any>
      <allow_inactive>no</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/network-recover</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
EOF

chmod 644 "$PKG_DIR/usr/share/polkit-1/actions/com.network-recover.policy"

echo -e "${GREEN}✅ Polkit policy created${NC}"

# Create DEBIAN control file (unchanged)
cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Maintainer: $MAINTAINER
Depends: bash (>= 4.0), iproute2, curl, network-manager, dnsutils, policykit-1
Recommends: network-manager, libvirt-clients, kubectl
Description: $DESCRIPTION
 .
 Network Recovery Tool is the Linux equivalent of the Windows
 "Diagnose and Repair Network Problems" feature.
 .
 It provides structured, layered diagnostics and repairs for:
  - Physical layer (carrier, link state)
  - IP layer (IPv4, IPv6, duplicate detection)
  - Routing (default routes, metrics)
  - Gateway (ARP, reachability)
  - Internet (multiple targets, ICMP + TCP)
  - DNS (resolution, security checks)
  - HTTPS (actual browsing simulation)
  - NetworkManager integration
  - Virtualization (KVM/Libvirt)
  - Kubernetes (optional)
 .
 No reboot required.
EOF

chmod 644 "$PKG_DIR/DEBIAN/control"

# Create post-install script (unchanged)
cat > "$PKG_DIR/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

# Update desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications/
fi

# Update icon cache
if command -v update-icon-caches &>/dev/null; then
    update-icon-caches /usr/share/icons/hicolor/
fi

echo ""
echo "=============================================="
echo "  ✅ Network Recovery Tool installed!"
echo "=============================================="
echo ""
echo "  Quick commands:"
echo "    sudo network-recover status"
echo "    sudo network-recover diagnose"
echo "    sudo network-recover repair"
echo ""
echo "  Panel icon added next to network icon"
echo "=============================================="
EOF

chmod 755 "$PKG_DIR/DEBIAN/postinst"

# Create post-removal script (unchanged)
cat > "$PKG_DIR/DEBIAN/postrm" << 'EOF'
#!/bin/bash
set -e

# Update desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications/
fi

# Update icon cache
if command -v update-icon-caches &>/dev/null; then
    update-icon-caches /usr/share/icons/hicolor/
fi
EOF

chmod 755 "$PKG_DIR/DEBIAN/postrm"

echo -e "${GREEN}✅ DEBIAN control files created${NC}"

# Create documentation (unchanged)
cat > "$PKG_DIR/usr/share/doc/$PACKAGE_NAME/README" << 'EOF'
Network Recovery Tool v1.1.1

Quick Start:
  sudo network-recover status     - Check network health
  sudo network-recover diagnose   - Run diagnostics
  sudo network-recover repair     - Diagnose and repair

Documentation:
  Full documentation at: https://github.com/cypso05/Linux_Network-Recovery-Tool
EOF

echo -e "${GREEN}✅ Documentation created${NC}"

# Build the package
echo ""
echo -e "${BLUE}📦 Building .deb package...${NC}"
cd "$BUILD_DIR"
dpkg-deb --build "$PACKAGE_NAME-$VERSION" 2>/dev/null
mv "$PACKAGE_NAME-$VERSION.deb" "../${PACKAGE_NAME}_${VERSION}_all.deb"
cd ..

echo ""
echo "=============================================="
echo -e "${GREEN}  ✅ PACKAGE BUILT SUCCESSFULLY!${NC}"
echo "=============================================="
echo ""
echo "📦 Package: ${PACKAGE_NAME}_${VERSION}_all.deb"
echo "📏 Size: $(du -h ${PACKAGE_NAME}_${VERSION}_all.deb 2>/dev/null | awk '{print $1}')"
echo ""
echo "📌 Install it:"
echo "  sudo dpkg -i ${PACKAGE_NAME}_${VERSION}_all.deb"
echo ""
echo "📌 Upload to GitHub Releases:"
echo "  https://github.com/cypso05/Linux_Network-Recovery-Tool/releases"
echo ""
echo "=============================================="