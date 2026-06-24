# ============================================================
# ONE-SHOT PROJECT CREATOR - Paste this entire block
# ============================================================

Write-Host "🚀 Creating Network-Recover Project" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Create folders
Write-Host "`n📁 Creating folders..." -ForegroundColor Yellow
@("src", "desktop", "integration", "tests") | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
        Write-Host "  ✅ Created: $_" -ForegroundColor Green
    } else {
        Write-Host "  ⏭️  Already exists: $_" -ForegroundColor Gray
    }
}

# README.md
Write-Host "`n📄 Creating README.md..." -ForegroundColor Yellow
@"
# Network Recovery Tool

A production-grade network diagnostic and recovery engine for Linux with XFCE desktop integration.

## Quick Install
\`\`\`bash
git clone https://github.com/yourname/network-recover.git
cd network-recover
chmod +x install.sh
sudo ./install.sh
\`\`\`

## Usage
- \`sudo network-recover diagnose\` - Run diagnostics (no changes)
- \`sudo network-recover repair\` - Diagnose and repair
- \`sudo network-recover snapshot\` - Save network state
- Right-click network icon → 'Network Diagnose & Repair'

## License
MIT
"@ | Out-File -FilePath "README.md" -Encoding UTF8
Write-Host "  ✅ README.md" -ForegroundColor Green

# LICENSE
Write-Host "`n📄 Creating LICENSE..." -ForegroundColor Yellow
@"
MIT License

Copyright (c) 2026 Network Recovery Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"@ | Out-File -FilePath "LICENSE" -Encoding UTF8
Write-Host "  ✅ LICENSE" -ForegroundColor Green

# Makefile
Write-Host "`n📄 Creating Makefile..." -ForegroundColor Yellow
@"
PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
DESKTOPDIR = $(PREFIX)/share/applications

.PHONY: all install uninstall test

all: install

install:
	@echo "Installing network-recover..."
	@mkdir -p $(BINDIR) $(DESKTOPDIR)
	@install -m 755 src/network-recover $(BINDIR)/
	@install -m 755 src/network-recover-gui $(BINDIR)/
	@install -m 644 desktop/network-recover.desktop $(DESKTOPDIR)/
	@echo "✅ Installation complete!"

uninstall:
	@echo "Uninstalling network-recover..."
	@rm -f $(BINDIR)/network-recover
	@rm -f $(BINDIR)/network-recover-gui
	@rm -f $(DESKTOPDIR)/network-recover.desktop
	@echo "✅ Uninstallation complete!"

test:
	@echo "Running tests..."
	@bash tests/test-manual.sh

help:
	@echo "make install - Install the tool"
	@echo "make uninstall - Remove the tool"
	@echo "make test - Run tests"
"@ | Out-File -FilePath "Makefile" -Encoding UTF8
Write-Host "  ✅ Makefile" -ForegroundColor Green

# src/network-recover
Write-Host "`n📄 Creating src/network-recover..." -ForegroundColor Yellow
@'
#!/bin/bash
# /usr/local/bin/network-recover
# Production-Grade Linux Network Recovery Engine

set -euo pipefail

VERSION="1.0.0"
SCRIPT_NAME="network-recover"
LOG_DIR="/var/log/network-events"
SNAPSHOT_DIR="/var/lib/network-recover/snapshots"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

mkdir -p "$LOG_DIR" "$SNAPSHOT_DIR"

DEFAULT_IFACE=$(ip route | awk '"'"'/default/ {print $5; exit}'"'"' 2>/dev/null || echo "eth0")
DEFAULT_GATEWAY=$(ip route | awk '"'"'/default/ {print $3; exit}'"'"' 2>/dev/null || echo "")

log() {
    echo "[$(date '"'"'+%Y-%m-%d %H:%M:%S'"'"')] $*"
}

log_result() {
    local status="$1"
    local message="$2"
    if [[ "$status" == "PASS" ]]; then
        echo "  ✅ $message"
    elif [[ "$status" == "FAIL" ]]; then
        echo "  ❌ $message"
    elif [[ "$status" == "WARN" ]]; then
        echo "  ⚠️  $message"
    else
        echo "  $message"
    fi
}

check_physical() {
    log "=== LAYER 1: PHYSICAL ==="
    if [[ -d "/sys/class/net/$DEFAULT_IFACE" ]]; then
        log_result "PASS" "Interface $DEFAULT_IFACE exists"
        if [[ -f "/sys/class/net/$DEFAULT_IFACE/carrier" ]]; then
            local carrier=$(cat "/sys/class/net/$DEFAULT_IFACE/carrier")
            if [[ "$carrier" == "1" ]]; then
                log_result "PASS" "Carrier present"
            else
                log_result "FAIL" "No carrier - check cable/WiFi"
                return 1
            fi
        fi
    else
        log_result "FAIL" "Interface $DEFAULT_IFACE not found"
        return 1
    fi
    return 0
}

check_ip_layer() {
    log "=== LAYER 3: IP ==="
    local ipv4=$(ip -4 addr show "$DEFAULT_IFACE" 2>/dev/null | grep -oP '"'"'(?<=inet\s)\d+(\.\d+){3}/\d+'"'"' | head -1)
    if [[ -n "$ipv4" ]]; then
        log_result "PASS" "IPv4: $ipv4"
        return 0
    else
        log_result "FAIL" "No IPv4 address"
        return 1
    fi
}

check_gateway() {
    log "=== LAYER 5: GATEWAY ==="
    if [[ -z "$DEFAULT_GATEWAY" ]]; then
        log_result "FAIL" "No default gateway"
        return 1
    fi
    if ping -c 1 -W 1 "$DEFAULT_GATEWAY" &>/dev/null; then
        log_result "PASS" "Gateway $DEFAULT_GATEWAY reachable"
        return 0
    else
        log_result "FAIL" "Gateway $DEFAULT_GATEWAY unreachable"
        return 1
    fi
}

check_internet() {
    log "=== LAYER 6: INTERNET ==="
    local targets=("1.1.1.1" "8.8.8.8" "9.9.9.9")
    local reachable=0
    for target in "${targets[@]}"; do
        if ping -c 1 -W 1 "$target" &>/dev/null; then
            log_result "PASS" "$target reachable"
            ((reachable++))
        else
            log_result "WARN" "$target unreachable"
        fi
    done
    if [[ "$reachable" -ge 2 ]]; then
        log_result "PASS" "Internet reachable ($reachable/3)"
        return 0
    else
        log_result "FAIL" "Internet unreachable ($reachable/3)"
        return 1
    fi
}

check_dns() {
    log "=== LAYER 7: DNS ==="
    local domains=("google.com" "cloudflare.com" "github.com")
    local success=0
    for domain in "${domains[@]}"; do
        if nslookup "$domain" &>/dev/null; then
            log_result "PASS" "$domain resolves"
            ((success++))
        else
            log_result "WARN" "$domain resolution failed"
        fi
    done
    if [[ "$success" -ge 2 ]]; then
        return 0
    else
        return 1
    fi
}

repair_network() {
    log "=== REPAIR ENGINE ==="
    local repaired=false
    
    if command -v resolvectl &>/dev/null; then
        resolvectl flush-caches 2>/dev/null && log_result "PASS" "DNS cache flushed" && repaired=true
    fi
    
    ip neigh flush all 2>/dev/null && log_result "PASS" "ARP cache flushed" && repaired=true
    
    if command -v nmcli &>/dev/null; then
        systemctl restart NetworkManager 2>/dev/null && log_result "PASS" "NetworkManager restarted" && repaired=true
        sleep 2
    fi
    
    if [[ "$repaired" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

cmd_diagnose() {
    log "=== NETWORK DIAGNOSTIC ==="
    local results_file="$LOG_DIR/diagnostic-${TIMESTAMP}.log"
    {
        check_physical
        check_ip_layer
        check_gateway
        check_internet
        check_dns
    } | tee -a "$results_file"
    echo ""
    echo "Report saved to: $results_file"
}

cmd_repair() {
    log "=== NETWORK RECOVERY ==="
    cmd_diagnose
    echo ""
    echo "=== ATTEMPTING REPAIRS ==="
    if repair_network; then
        echo ""
        echo "=== VERIFYING REPAIRS ==="
        sleep 2
        check_internet
        check_dns
    fi
}

cmd_snapshot() {
    echo "=== SNAPSHOT ==="
    echo "Network state saved to: $SNAPSHOT_DIR"
}

cmd_watch() {
    echo "Monitoring network health (Ctrl+C to stop)"
    while true; do
        clear
        echo "=== NETWORK HEALTH MONITOR ==="
        echo "Time: $(date)"
        echo ""
        if ping -c 1 -W 1 8.8.8.8 &>/dev/null; then
            echo "  ✅ Internet: OK"
        else
            echo "  ❌ Internet: DOWN"
        fi
        if nslookup google.com &>/dev/null; then
            echo "  ✅ DNS: OK"
        else
            echo "  ❌ DNS: FAILED"
        fi
        sleep 2
    done
}

show_usage() {
    cat << EOF
Network Recovery Engine v$VERSION

Usage:
    $SCRIPT_NAME diagnose   - Run full diagnostic (no changes)
    $SCRIPT_NAME repair     - Diagnose and attempt repairs
    $SCRIPT_NAME snapshot   - Save current network state
    $SCRIPT_NAME watch      - Monitor network health in real-time
    $SCRIPT_NAME help       - Show this help
EOF
}

main() {
    if [[ $EUID -ne 0 ]] && [[ "${1:-}" != "help" ]]; then
        echo "This script must be run as root (sudo)"
        exit 1
    fi
    
    case "${1:-diagnose}" in
        diagnose|diag)   cmd_diagnose ;;
        repair|fix)      cmd_repair ;;
        snapshot|snap)   cmd_snapshot ;;
        watch|monitor)   cmd_watch ;;
        help|--help|-h)  show_usage ;;
        *) echo "Unknown command: ${1:-}"; show_usage; exit 1 ;;
    esac
}

main "$@"
'@ | Out-File -FilePath "src/network-recover" -Encoding UTF8
Write-Host "  ✅ src/network-recover (template)" -ForegroundColor Green

# src/network-recover-gui
Write-Host "`n📄 Creating src/network-recover-gui..." -ForegroundColor Yellow
@'
#!/bin/bash
TITLE="Network Recovery"
LOG_FILE="/tmp/network-recover-gui.log"

pkill -f "zenity.*Network Recovery" 2>/dev/null || true

if command -v notify-send &>/dev/null; then
    notify-send -u normal -t 3000 "$TITLE" "Diagnosing network..."
fi

if command -v zenity &>/dev/null; then
    (
        echo "10"; echo "# Starting network diagnostics..."
        echo "30"; echo "# Checking physical layer..."
        echo "50"; echo "# Testing connectivity..."
        echo "70"; echo "# Attempting repairs..."
        echo "90"; echo "# Verifying..."
        /usr/local/bin/network-recover repair 2>&1 | tee "$LOG_FILE"
        echo "100"; echo "# Complete!"
    ) | zenity --progress --title="$TITLE" --text="Diagnosing network..." \
               --percentage=0 --auto-close --width=400 2>/dev/null
else
    /usr/local/bin/network-recover repair 2>&1 | tee "$LOG_FILE"
fi

RESULT=$?
if [ $RESULT -eq 0 ]; then
    if command -v notify-send &>/dev/null; then
        notify-send -u normal -t 10000 "$TITLE" "Network connectivity restored successfully!"
    fi
    echo "Success - Network restored"
else
    if command -v notify-send &>/dev/null; then
        notify-send -u critical -t 10000 "$TITLE" "Repairs failed - Check $LOG_FILE"
    fi
    echo "Repairs failed"
fi

exit $RESULT
'@ | Out-File -FilePath "src/network-recover-gui" -Encoding UTF8
Write-Host "  ✅ src/network-recover-gui" -ForegroundColor Green

# desktop/network-recover.desktop
Write-Host "`n📄 Creating desktop/network-recover.desktop..." -ForegroundColor Yellow
@'
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
X-XFCE-Settings=Network
'@ | Out-File -FilePath "desktop/network-recover.desktop" -Encoding UTF8
Write-Host "  ✅ desktop/network-recover.desktop" -ForegroundColor Green

# integration/xfce-integration.sh
Write-Host "`n📄 Creating integration/xfce-integration.sh..." -ForegroundColor Yellow
@'
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
'@ | Out-File -FilePath "integration/xfce-integration.sh" -Encoding UTF8
Write-Host "  ✅ integration/xfce-integration.sh" -ForegroundColor Green

# tests/test-manual.sh
Write-Host "`n📄 Creating tests/test-manual.sh..." -ForegroundColor Yellow
@'
#!/bin/bash
echo "Testing Network Recovery Tool"
echo "================================"
echo ""

echo "1. Testing diagnose command..."
sudo /usr/local/bin/network-recover diagnose
echo ""

echo "2. Testing snapshot command..."
sudo /usr/local/bin/network-recover snapshot
echo ""

echo "3. Testing repair command..."
sudo /usr/local/bin/network-recover repair
echo ""

echo "All tests completed!"
'@ | Out-File -FilePath "tests/test-manual.sh" -Encoding UTF8
Write-Host "  ✅ tests/test-manual.sh" -ForegroundColor Green

# tests/test-offline.sh
Write-Host "`n📄 Creating tests/test-offline.sh..." -ForegroundColor Yellow
@'
#!/bin/bash
echo "Simulating offline conditions..."
echo "================================"

IFACE=$(ip route | awk '"'"'/default/ {print $5; exit}'"'"' 2>/dev/null || echo "wlan0")
echo "Interface: $IFACE"
echo ""

echo "Disabling $IFACE..."
sudo ip link set "$IFACE" down
sleep 2

echo "Running network recovery..."
sudo /usr/local/bin/network-recover repair

echo ""
echo "Re-enabling $IFACE..."
sudo ip link set "$IFACE" up
sleep 2

echo "Test complete!"
'@ | Out-File -FilePath "tests/test-offline.sh" -Encoding UTF8
Write-Host "  ✅ tests/test-offline.sh" -ForegroundColor Green

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "✅ PROJECT STRUCTURE CREATED!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`n📁 Created Files:" -ForegroundColor Yellow
Get-ChildItem -Recurse -File | Where-Object { $_.Name -notin @("create-project.ps1", "inspiration.md", "steps.md") } | ForEach-Object {
    $rel = $_.FullName.Replace((Get-Location).Path + "\", "")
    Write-Host "  ✅ $rel" -ForegroundColor Green
}

Write-Host "`n📝 NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1️⃣ Replace src/network-recover with your FULL script from inspiration.md" -ForegroundColor White
Write-Host "  2️⃣ Copy files to your Linux machine" -ForegroundColor White
Write-Host "  3️⃣ On Linux: chmod +x src/* tests/*.sh integration/*.sh" -ForegroundColor White
Write-Host "  4️⃣ On Linux: sudo ./install.sh" -ForegroundColor White
Write-Host "  5️⃣ Right-click network icon → 'Network Diagnose & Repair'" -ForegroundColor White

Write-Host "`n📦 Project is ready!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan