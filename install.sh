#!/bin/bash
#===============================================================================
# Network Recovery Tool - Installer
# Version: 1.1.1
# Installs the tool, GUI wrapper, web interface, modular components, 
# XFCE integration, icons, and polkit rules
#===============================================================================

set -euo pipefail

readonly VERSION="1.1.1"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly BIN_DIR="/usr/local/bin"
readonly LIB_DIR="/usr/local/lib/network-recover"
readonly APP_DIR="/usr/share/applications"
readonly POLKIT_DIR="/usr/share/polkit-1/actions"
readonly LOG_DIR="/var/log/network-events"
readonly SNAPSHOT_DIR="/var/lib/network-recover/snapshots"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse arguments
UNINSTALL=false
NO_GUI=false
SKIP_DEPS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall|-u)
            UNINSTALL=true
            shift
            ;;
        --no-gui)
            NO_GUI=true
            shift
            ;;
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        --help|-h)
            echo "Network Recovery Tool Installer v$VERSION"
            echo ""
            echo "Usage: sudo ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --uninstall, -u   Uninstall the tool"
            echo "  --no-gui          Skip GUI dependencies (headless server)"
            echo "  --skip-deps       Skip dependency installation"
            echo "  --help, -h        Show this help"
            echo ""
            echo "Examples:"
            echo "  sudo ./install.sh              # Install"
            echo "  sudo ./install.sh --uninstall  # Uninstall"
            echo "  sudo ./install.sh --no-gui     # Install without GUI"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

#===============================================================================
# UNINSTALL
#===============================================================================

if [[ "$UNINSTALL" == "true" ]]; then
    echo ""
    echo "=============================================="
    echo " Network Recovery Tool v$VERSION - Uninstaller"
    echo "=============================================="
    echo ""
    
    echo "📌 Removing binaries..."
    rm -f "$BIN_DIR/network-recover" && echo "  ✅ Removed: $BIN_DIR/network-recover" || echo "  ⚠️  Not found: $BIN_DIR/network-recover"
    rm -f "$BIN_DIR/network-recover-gui" && echo "  ✅ Removed: $BIN_DIR/network-recover-gui" || echo "  ⚠️  Not found: $BIN_DIR/network-recover-gui"
    rm -f "$BIN_DIR/network-recover-web" && echo "  ✅ Removed: $BIN_DIR/network-recover-web" || echo "  ⚠️  Not found: $BIN_DIR/network-recover-web"
    
    echo "📌 Removing desktop entry..."
    rm -f "$APP_DIR/network-recover.desktop" && echo "  ✅ Removed: $APP_DIR/network-recover.desktop" || echo "  ⚠️  Not found"
    
    echo "📌 Removing polkit policy..."
    rm -f "$POLKIT_DIR/com.network-recover.policy" && echo "  ✅ Removed: $POLKIT_DIR/com.network-recover.policy" || echo "  ⚠️  Not found"
    
    echo "📌 Removing modules..."
    rm -rf "$LIB_DIR" && echo "  ✅ Removed: $LIB_DIR" || echo "  ⚠️  Not found"
    
    echo "📌 Removing icons..."
    rm -f "/usr/share/icons/hicolor/scalable/apps/network-recover.svg" 2>/dev/null || true
    rm -f "/usr/share/icons/hicolor/48x48/apps/network-recover.png" 2>/dev/null || true
    echo "  ✅ Icons removed"
    
    echo "📌 Removing logs and snapshots..."
    rm -rf "$LOG_DIR" && echo "  ✅ Removed: $LOG_DIR" || echo "  ⚠️  Not found"
    rm -rf "$SNAPSHOT_DIR" && echo "  ✅ Removed: $SNAPSHOT_DIR" || echo "  ⚠️  Not found"
    
    echo ""
    echo "=============================================="
    echo "  ✅ UNINSTALLATION COMPLETE!"
    echo "=============================================="
    exit 0
fi

#===============================================================================
# MAIN INSTALLATION
#===============================================================================

echo ""
echo "=============================================="
echo " Network Recovery Tool v$VERSION - Installer"
echo "=============================================="
echo ""

# Check root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}❌ This installer must be run as root (sudo)${NC}"
    exit 1
fi

# Detect distribution
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
echo -e "${GREEN}✅ Detected distribution: $DISTRO${NC}"

# Step 1: Install dependencies
if [[ "$SKIP_DEPS" != "true" ]]; then
    echo ""
    echo "📦 Installing dependencies..."
    
    install_deps_debian() {
        apt-get update -qq
        local deps="curl iproute2 bridge-utils ethtool netcat-openbsd dnsutils network-manager policykit-1 python3"
        if [[ "$NO_GUI" != "true" ]]; then
            deps="$deps zenity libnotify-bin"
        fi
        apt-get install -y -qq $deps 2>/dev/null || true
    }
    
    install_deps_rhel() {
        local deps="curl iproute bridge-utils ethtool nmap-ncat bind-utils NetworkManager polkit python3"
        if [[ "$NO_GUI" != "true" ]]; then
            deps="$deps zenity libnotify"
        fi
        yum install -y -q $deps 2>/dev/null || true
    }
    
    install_deps_arch() {
        local deps="curl iproute2 bridge-utils ethtool openbsd-netcat bind networkmanager polkit python"
        if [[ "$NO_GUI" != "true" ]]; then
            deps="$deps zenity libnotify"
        fi
        pacman -S --noconfirm --needed $deps 2>/dev/null || true
    }
    
    case "$DISTRO" in
        debian|ubuntu|mx|linuxmint|pop)
            install_deps_debian
            ;;
        fedora|rhel|centos|rocky|alma)
            install_deps_rhel
            ;;
        arch|manjaro|endeavouros)
            install_deps_arch
            ;;
        *)
            echo -e "${YELLOW}⚠️  Unknown distribution - please install dependencies manually:${NC}"
            echo "   core: curl, iproute2, bridge-utils, ethtool, netcat, dnsutils, network-manager, polkit, python3"
            if [[ "$NO_GUI" != "true" ]]; then
                echo "   gui:  zenity, libnotify"
            fi
            ;;
    esac
    
    echo -e "${GREEN}✅ Dependencies installed${NC}"
else
    echo -e "${YELLOW}⚠️  Skipping dependency installation${NC}"
fi

# Step 2: Create directories
echo ""
echo "📁 Creating directories..."
mkdir -p "$LOG_DIR" "$SNAPSHOT_DIR"
chmod 755 "$LOG_DIR" "$SNAPSHOT_DIR"
echo -e "${GREEN}✅ Directories created${NC}"

# Step 3: Install core engine
echo ""
echo "📋 Installing core engine..."
if [[ -f "$SCRIPT_DIR/src/network-recover" ]]; then
    cp "$SCRIPT_DIR/src/network-recover" "$BIN_DIR/network-recover"
    chmod 755 "$BIN_DIR/network-recover"
    echo -e "${GREEN}✅ Core engine installed to $BIN_DIR/network-recover${NC}"
else
    echo -e "${RED}❌ src/network-recover not found!${NC}"
    exit 1
fi

# Step 4: Install GUI wrapper
if [[ "$NO_GUI" != "true" ]]; then
    echo ""
    echo "🖥️  Installing GUI wrapper..."
    if [[ -f "$SCRIPT_DIR/src/network-recover-gui" ]]; then
        cp "$SCRIPT_DIR/src/network-recover-gui" "$BIN_DIR/network-recover-gui"
        chmod 755 "$BIN_DIR/network-recover-gui"
        echo -e "${GREEN}✅ GUI wrapper installed to $BIN_DIR/network-recover-gui${NC}"
    else
        echo -e "${YELLOW}⚠️  GUI wrapper not found - skipping${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Skipping GUI installation (--no-gui)${NC}"
fi

# Step 5: Install modular components
echo ""
echo "📋 Installing modular components..."
mkdir -p "$LIB_DIR"

MODULES_INSTALLED=0
MODULES_TOTAL=0

if [[ -d "$SCRIPT_DIR/diagnostics" ]]; then
    MODULES_TOTAL=$((MODULES_TOTAL + 1))
    cp -r "$SCRIPT_DIR/diagnostics" "$LIB_DIR/"
    chmod -R 755 "$LIB_DIR/diagnostics"
    diag_count=$(ls -1 "$LIB_DIR/diagnostics" 2>/dev/null | wc -l)
    echo -e "  ✅ diagnostics/ installed ($diag_count modules)"
    MODULES_INSTALLED=$((MODULES_INSTALLED + 1))
else
    echo -e "  ${YELLOW}⚠️  diagnostics/ not found - skipping${NC}"
fi

if [[ -d "$SCRIPT_DIR/repairs" ]]; then
    MODULES_TOTAL=$((MODULES_TOTAL + 1))
    cp -r "$SCRIPT_DIR/repairs" "$LIB_DIR/"
    chmod -R 755 "$LIB_DIR/repairs"
    repair_count=$(ls -1 "$LIB_DIR/repairs" 2>/dev/null | wc -l)
    echo -e "  ✅ repairs/ installed ($repair_count modules)"
    MODULES_INSTALLED=$((MODULES_INSTALLED + 1))
else
    echo -e "  ${YELLOW}⚠️  repairs/ not found - skipping${NC}"
fi

if [[ -d "$SCRIPT_DIR/collectors" ]]; then
    MODULES_TOTAL=$((MODULES_TOTAL + 1))
    cp -r "$SCRIPT_DIR/collectors" "$LIB_DIR/"
    chmod -R 755 "$LIB_DIR/collectors"
    coll_count=$(ls -1 "$LIB_DIR/collectors" 2>/dev/null | wc -l)
    echo -e "  ✅ collectors/ installed ($coll_count modules)"
    MODULES_INSTALLED=$((MODULES_INSTALLED + 1))
else
    echo -e "  ${YELLOW}⚠️  collectors/ not found - skipping${NC}"
fi

if [[ "$MODULES_INSTALLED" -eq "$MODULES_TOTAL" ]] && [[ "$MODULES_TOTAL" -gt 0 ]]; then
    echo -e "${GREEN}✅ All modular components installed ($MODULES_INSTALLED/$MODULES_TOTAL)${NC}"
elif [[ "$MODULES_INSTALLED" -gt 0 ]]; then
    echo -e "${YELLOW}⚠️  Partial modular install ($MODULES_INSTALLED/$MODULES_TOTAL)${NC}"
else
    echo -e "${YELLOW}⚠️  No modular components found - core engine is self-contained${NC}"
fi

# Step 5.5: Install icons
echo ""
echo "🎨 Installing icons..."

ICON_SOURCE="$SCRIPT_DIR/icons"
ICON_DEST="/usr/share/icons/hicolor"

if [[ -d "$ICON_SOURCE" ]]; then
    # Install scalable icon
    if [[ -f "$ICON_SOURCE/network-recover.svg" ]]; then
        mkdir -p "$ICON_DEST/scalable/apps"
        cp "$ICON_SOURCE/network-recover.svg" "$ICON_DEST/scalable/apps/"
        echo "  ✅ SVG icon installed"
    fi
    
    # Install 48x48 icon
    if [[ -f "$ICON_SOURCE/network-recover.png" ]]; then
        mkdir -p "$ICON_DEST/48x48/apps"
        cp "$ICON_SOURCE/network-recover.png" "$ICON_DEST/48x48/apps/"
        echo "  ✅ PNG icon installed"
    fi
    
    # Update icon cache
    if command -v update-icon-caches &>/dev/null; then
        update-icon-caches /usr/share/icons/hicolor/
        echo "  ✅ Icon cache updated"
    fi
else
    echo "  ⚠️  icons/ folder not found - using system icons"
fi

# Step 5.6: Install web application
if [[ "$NO_GUI" != "true" ]]; then
    echo ""
    echo "🌐 Installing web application..."
    
    # Create web directory
    mkdir -p "$LIB_DIR/web"
    mkdir -p "$LIB_DIR/web/static"
    
    # Copy web server
    if [[ -f "$SCRIPT_DIR/web/server.py" ]]; then
        cp "$SCRIPT_DIR/web/server.py" "$LIB_DIR/web/"
        chmod 755 "$LIB_DIR/web/server.py"
        echo "  ✅ Web server installed"
    else
        echo "  ⚠️  web/server.py not found - skipping"
    fi
    
    # Copy static files
    if [[ -d "$SCRIPT_DIR/web/static" ]]; then
        cp -r "$SCRIPT_DIR/web/static"/* "$LIB_DIR/web/static/"
        echo "  ✅ Web UI files installed"
    else
        echo "  ⚠️  web/static/ not found - skipping"
    fi
    
    # Install web launcher
    if [[ -f "$SCRIPT_DIR/src/network-recover-web" ]]; then
        cp "$SCRIPT_DIR/src/network-recover-web" "$BIN_DIR/network-recover-web"
        chmod 755 "$BIN_DIR/network-recover-web"
        echo "  ✅ Web launcher installed to $BIN_DIR/network-recover-web"
    else
        echo "  ⚠️  src/network-recover-web not found - skipping"
    fi
    
    echo -e "${GREEN}✅ Web application installed${NC}"
else
    echo -e "${YELLOW}⚠️  Skipping web application installation (--no-gui)${NC}"
fi

# Step 6: Install desktop entry
echo ""
echo "📱 Installing desktop entry..."
if [[ -f "$SCRIPT_DIR/desktop/network-recover.desktop" ]]; then
    cp "$SCRIPT_DIR/desktop/network-recover.desktop" "$APP_DIR/network-recover.desktop"
    chmod 644 "$APP_DIR/network-recover.desktop"
    echo -e "${GREEN}✅ Desktop entry installed${NC}"
else
    # Create it from scratch if missing
    cat > "$APP_DIR/network-recover.desktop" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Network Recovery Tool
Comment=Diagnose and fix network connectivity issues
Exec=pkexec /usr/local/bin/network-recover-web
Icon=network-recover
Terminal=false
Categories=Network;
StartupNotify=true
Actions=diagnose;repair;status;snapshot;watch;cli-gui

[Desktop Action diagnose]
Name=Diagnose Network
Exec=pkexec /usr/local/bin/network-recover-web

[Desktop Action repair]
Name=Repair Network
Exec=pkexec /usr/local/bin/network-recover-web

[Desktop Action status]
Name=Network Status
Exec=pkexec /usr/local/bin/network-recover-web

[Desktop Action snapshot]
Name=Save Snapshot
Exec=pkexec /usr/local/bin/network-recover-web

[Desktop Action watch]
Name=Monitor Network
Exec=pkexec /usr/local/bin/network-recover-web

[Desktop Action cli-gui]
Name=CLI GUI (Zenity)
Exec=pkexec /usr/local/bin/network-recover-gui
EOF
    chmod 644 "$APP_DIR/network-recover.desktop"
    echo -e "${GREEN}✅ Desktop entry created${NC}"
fi

# Step 7: Install polkit policy
echo ""
echo "🔐 Installing polkit policy..."
cat > "$POLKIT_DIR/com.network-recover.policy" << 'EOF'
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
  <action id="com.network-recover.gui">
    <description>Run network diagnostics and repair (GUI)</description>
    <message>Authentication is required to diagnose and repair network connectivity</message>
    <icon_name>network-recover</icon_name>
    <defaults>
      <allow_any>no</allow_any>
      <allow_inactive>no</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/network-recover-gui</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
EOF
chmod 644 "$POLKIT_DIR/com.network-recover.policy"
echo -e "${GREEN}✅ Polkit policy installed${NC}"

# Step 8: XFCE panel integration
echo ""
echo "🔧 Setting up XFCE panel integration..."

setup_xfce_panel() {
    mkdir -p /home/*/.local/share/applications 2>/dev/null || true
    mkdir -p /root/.local/share/applications 2>/dev/null || true
    
    cp "$APP_DIR/network-recover.desktop" /etc/skel/.local/share/applications/ 2>/dev/null || true
    
    for user_home in /home/*; do
        if [[ -d "$user_home" ]]; then
            mkdir -p "$user_home/.local/share/applications"
            cp "$APP_DIR/network-recover.desktop" "$user_home/.local/share/applications/"
            chown -R "$(basename "$user_home"):$(basename "$user_home")" "$user_home/.local/share/applications/" 2>/dev/null || true
        fi
    done
    
    if pgrep -x "xfce4-panel" > /dev/null; then
        echo -e "${GREEN}✅ XFCE panel detected - launcher available in panel preferences${NC}"
        echo ""
        echo "   To add to your panel right now:"
        echo "   1. Right-click panel → Panel → Add New Items"
        echo "   2. Search for 'Network Recovery Tool'"
        echo "   3. Click 'Add'"
        echo ""
        xfce4-panel --add=launcher 2>/dev/null || true
    else
        echo -e "${YELLOW}⚠️  XFCE panel not running - launcher will appear after next login${NC}"
    fi
}

setup_xfce_panel

# Step 9: Update desktop database
echo ""
echo "🔄 Updating desktop database..."
update-desktop-database "$APP_DIR" 2>/dev/null || true
echo -e "${GREEN}✅ Done${NC}"

# Step 10: Verify installation
echo ""
echo "=============================================="
echo "    VERIFYING INSTALLATION"
echo "=============================================="
echo ""

VERIFY_OK=true

# Core engine
if [[ -x "$BIN_DIR/network-recover" ]]; then
    echo -e "  ✅ Core engine: $BIN_DIR/network-recover"
else
    echo -e "  ❌ Core engine: MISSING"
    VERIFY_OK=false
fi

# GUI wrapper
if [[ -x "$BIN_DIR/network-recover-gui" ]]; then
    echo -e "  ✅ GUI wrapper: $BIN_DIR/network-recover-gui"
else
    echo -e "  ⚠️  GUI wrapper: missing (optional)"
fi

# Web launcher
if [[ -x "$BIN_DIR/network-recover-web" ]]; then
    echo -e "  ✅ Web launcher: $BIN_DIR/network-recover-web"
else
    echo -e "  ⚠️  Web launcher: missing (optional)"
fi

# Web application files
if [[ -f "$LIB_DIR/web/server.py" ]]; then
    echo -e "  ✅ Web server: $LIB_DIR/web/server.py"
else
    echo -e "  ⚠️  Web server: missing (optional)"
fi

if [[ -d "$LIB_DIR/web/static" ]]; then
    echo -e "  ✅ Web UI: $LIB_DIR/web/static"
else
    echo -e "  ⚠️  Web UI: missing (optional)"
fi

# Modular components
if [[ -d "$LIB_DIR/diagnostics" ]]; then
    echo -e "  ✅ Diagnostics: $(ls -1 "$LIB_DIR/diagnostics" 2>/dev/null | wc -l) modules"
else
    echo -e "  ⚠️  Diagnostics: not installed (core engine is self-contained)"
fi

if [[ -d "$LIB_DIR/repairs" ]]; then
    echo -e "  ✅ Repairs: $(ls -1 "$LIB_DIR/repairs" 2>/dev/null | wc -l) modules"
else
    echo -e "  ⚠️  Repairs: not installed (core engine is self-contained)"
fi

if [[ -d "$LIB_DIR/collectors" ]]; then
    echo -e "  ✅ Collectors: $(ls -1 "$LIB_DIR/collectors" 2>/dev/null | wc -l) modules"
else
    echo -e "  ⚠️  Collectors: not installed (core engine is self-contained)"
fi

# Desktop entry
if [[ -f "$APP_DIR/network-recover.desktop" ]]; then
    echo -e "  ✅ Desktop entry: $APP_DIR/network-recover.desktop"
else
    echo -e "  ❌ Desktop entry: MISSING"
    VERIFY_OK=false
fi

# Polkit policy
if [[ -f "$POLKIT_DIR/com.network-recover.policy" ]]; then
    echo -e "  ✅ Polkit policy: installed"
else
    echo -e "  ❌ Polkit policy: MISSING"
    VERIFY_OK=false
fi

# Icons
if [[ -f "/usr/share/icons/hicolor/scalable/apps/network-recover.svg" ]]; then
    echo -e "  ✅ SVG icon: installed"
else
    echo -e "  ⚠️  SVG icon: missing (optional)"
fi

if [[ -f "/usr/share/icons/hicolor/48x48/apps/network-recover.png" ]]; then
    echo -e "  ✅ PNG icon: installed"
else
    echo -e "  ⚠️  PNG icon: missing (optional)"
fi

# Log directories
if [[ -d "$LOG_DIR" ]]; then
    echo -e "  ✅ Log directory: $LOG_DIR"
else
    echo -e "  ❌ Log directory: MISSING"
    VERIFY_OK=false
fi

if [[ -d "$SNAPSHOT_DIR" ]]; then
    echo -e "  ✅ Snapshot directory: $SNAPSHOT_DIR"
else
    echo -e "  ❌ Snapshot directory: MISSING"
    VERIFY_OK=false
fi

echo ""

if [[ "$VERIFY_OK" == "true" ]]; then
    echo "=============================================="
    echo "  ✅ INSTALLATION COMPLETE!"
    echo "=============================================="
    echo ""
    echo "  Quick commands:"
    echo "    sudo network-recover diagnose"
    echo "    sudo network-recover repair"
    echo "    sudo network-recover status"
    echo "    sudo network-recover snapshot"
    echo "    sudo network-recover watch"
    echo ""
    echo "  Web Interface:"
    echo "    pkexec /usr/local/bin/network-recover-web"
    echo "    Or use the desktop launcher"
    echo ""
    echo "  To add the panel launcher:"
    echo "    Right-click panel → Panel → Add New Items"
    echo "    Look for 'Network Recovery Tool'"
    echo ""
    echo "  Or run from terminal:"
    echo "    pkexec /usr/local/bin/network-recover-gui  (Zenity)"
    echo "    pkexec /usr/local/bin/network-recover-web  (Web UI)"
    echo ""
else
    echo "=============================================="
    echo "  ⚠️  INSTALLATION COMPLETED WITH WARNINGS"
    echo "=============================================="
    echo "  Check the items marked ❌ above"
    echo ""
fi