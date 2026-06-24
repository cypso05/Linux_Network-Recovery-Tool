#!/bin/bash
echo "Installing Network Recovery for XFCE..."

if [ ! -f /usr/local/bin/network-recover ]; then
    echo "network-recover not found at /usr/local/bin/"
    exit 1
fi

apt-get update -qq && apt-get install -y libnotify-bin zenity 2>/dev/null || true

cat > /usr/share/applications/network-recover.desktop << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Network Diagnose & Repair
Comment=Diagnose and fix network connectivity issues
Exec=pkexec /usr/local/bin/network-recover-gui
Icon=network-wireless
Terminal=false
Categories=System;Network;
StartupNotify=true
EOF

mkdir -p ~/.local/share/applications
cp /usr/share/applications/network-recover.desktop ~/.local/share/applications/

if pgrep -x "xfce4-panel" > /dev/null; then
    pkill -x xfce4-panel 2>/dev/null || true
    sleep 1
    xfce4-panel --display :0.0 &
    echo "XFCE panel restarted"
fi

if pgrep -x "nm-applet" > /dev/null; then
    pkill -x nm-applet 2>/dev/null || true
    sleep 1
    nm-applet --display :0.0 &
    echo "nm-applet restarted"
fi

echo ""
echo "=========================================="
echo "XFCE INTEGRATION COMPLETE"
echo "=========================================="
echo ""
echo "Right-click your network icon → 'Network Diagnose & Repair'"
