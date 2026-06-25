#!/bin/bash
# tests/test-offline.sh - Simulate offline conditions and test recovery
# Usage: ./test-offline.sh [--diagnose-only] [--interface IFACE]

set -euo pipefail

# Parse arguments
DIAGNOSE_ONLY=false
TEST_IFACE=""
REPAIR_TIMEOUT=60  # seconds to wait for repair before forcing restoration

while [[ $# -gt 0 ]]; do
    case $1 in
        --diagnose-only|-d)
            DIAGNOSE_ONLY=true
            shift
            ;;
        --interface|-i)
            TEST_IFACE="$2"
            shift 2
            ;;
        --timeout|-t)
            REPAIR_TIMEOUT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--diagnose-only] [--interface IFACE] [--timeout SECONDS]"
            echo "  --diagnose-only  Run diagnose only (no repairs)"
            echo "  --interface      Specify interface to test (default: auto-detect)"
            echo "  --timeout        Timeout for repair command (default: 60s)"
            echo "  --help           Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

# Determine which network-recover binary to use
find_network_recover() {
    if command -v network-recover &>/dev/null; then
        echo "network-recover"
        return 0
    fi
    if [[ -f "./src/network-recover" ]] && [[ -x "./src/network-recover" ]]; then
        echo "./src/network-recover"
        return 0
    fi
    if [[ -f "./src/network-recover" ]]; then
        chmod +x ./src/network-recover
        echo "./src/network-recover"
        return 0
    fi
    echo ""
    return 1
}

NETWORK_RECOVER=$(find_network_recover)
if [[ -z "$NETWORK_RECOVER" ]]; then
    echo "❌ network-recover not found!"
    echo "   Please install with: sudo ./install.sh"
    echo "   Or run from the repo root: cd ~/Linux_Network-Recovery-Tool"
    exit 1
fi

echo "📌 Using: $NETWORK_RECOVER"
echo ""

echo "=============================================="
echo "  NETWORK OFFLINE TEST"
echo "=============================================="
echo ""

# Detect interface
if [[ -z "$TEST_IFACE" ]]; then
    IFACE=$(ip route | awk '/default/ {print $5; exit}' 2>/dev/null || echo "")
    if [[ -z "$IFACE" ]]; then
        # Fallback: find any interface with an IP
        IFACE=$(ip -4 addr show 2>/dev/null | grep -oP '^[0-9]+: \K[^:]+' | grep -v lo | head -1)
    fi
    [[ -z "$IFACE" ]] && IFACE="eth0"
else
    IFACE="$TEST_IFACE"
fi

echo "📌 Interface: $IFACE"

# Determine interface type
if [[ -d "/sys/class/net/$IFACE/wireless" ]] || [[ -d "/sys/class/net/$IFACE/phy80211" ]]; then
    IFACE_TYPE="wireless"
    echo "📌 Type: WiFi"
elif [[ -d "/sys/class/net/$IFACE/bridge" ]] || ip link show "$IFACE" 2>/dev/null | grep -q "bridge"; then
    IFACE_TYPE="bridge"
    echo "📌 Type: Bridge"
else
    IFACE_TYPE="ethernet"
    echo "📌 Type: Ethernet"
fi

# Check if interface exists
if [[ ! -d "/sys/class/net/$IFACE" ]]; then
    echo "❌ Interface $IFACE does not exist"
    exit 1
fi

# Save current state
echo ""
echo "📌 Current state:"
if ip link show "$IFACE" | grep -q "UP"; then
    echo "  ✅ Interface is UP"
else
    echo "  ⚠️  Interface is DOWN"
fi

# Use \K instead of lookbehind for grep portability
IP_ADDR=$(ip -4 addr show "$IFACE" 2>/dev/null | grep -oP 'inet\s\K[0-9.]+' | head -1)
echo "  IP: ${IP_ADDR:-None}"

GATEWAY=$(ip route | awk '/default/ {print $3; exit}' 2>/dev/null || echo "None")
echo "  Gateway: $GATEWAY"

# Save connection name if using NetworkManager
CONN_NAME=""
if command -v nmcli &>/dev/null; then
    CONN_NAME=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | grep ":${IFACE}$" | cut -d: -f1)
    if [[ -n "$CONN_NAME" ]]; then
        echo "  Connection: $CONN_NAME"
    fi
fi

# Test connectivity before disabling
echo ""
echo "📌 Testing connectivity before disabling..."
if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
    echo "  ✅ Internet reachable"
else
    echo "  ⚠️  Internet not reachable (test may be less useful)"
fi

echo ""
echo "=============================================="
echo "  SIMULATING OFFLINE CONDITIONS"
echo "=============================================="
echo ""

# Disable interface
echo "📌 Disabling $IFACE..."
if [[ "$IFACE_TYPE" == "wireless" ]]; then
    if command -v nmcli &>/dev/null; then
        sudo nmcli radio wifi off 2>/dev/null && echo "  ✅ WiFi disabled (nmcli)"
    else
        sudo ip link set "$IFACE" down 2>/dev/null && echo "  ✅ Interface down (ip link)"
    fi
else
    sudo ip link set "$IFACE" down 2>/dev/null && echo "  ✅ Interface down (ip link)"
fi

# Verify it's down
sleep 2
if ip link show "$IFACE" | grep -q "UP"; then
    echo "  ⚠️  Interface still UP - forced down may have failed"
fi

echo ""
echo "📌 Verifying network is down..."
if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
    echo "  ⚠️  Internet still reachable (test may not work)"
else
    echo "  ✅ Internet unreachable (as expected)"
fi

echo ""
echo "=============================================="
echo "  RUNNING NETWORK RECOVERY"
echo "=============================================="
echo ""

# Function to restore network regardless of repair outcome
restore_network() {
    echo ""
    echo "=============================================="
    echo "  RESTORING NETWORK"
    echo "=============================================="
    echo ""
    
    echo "📌 Re-enabling $IFACE..."
    if [[ "$IFACE_TYPE" == "wireless" ]]; then
        if command -v nmcli &>/dev/null; then
            sudo nmcli radio wifi on 2>/dev/null && echo "  ✅ WiFi enabled (nmcli)"
        else
            sudo ip link set "$IFACE" up 2>/dev/null && echo "  ✅ Interface up (ip link)"
        fi
    else
        sudo ip link set "$IFACE" up 2>/dev/null && echo "  ✅ Interface up (ip link)"
    fi
    
    echo "  ⏳ Waiting for interface to stabilize..."
    sleep 3
    
    if [[ -n "$CONN_NAME" ]] && command -v nmcli &>/dev/null; then
        echo "📌 Re-activating connection '$CONN_NAME'..."
        sudo nmcli con down "$CONN_NAME" 2>/dev/null || true
        sleep 1
        if sudo nmcli con up "$CONN_NAME" 2>/dev/null; then
            echo "  ✅ Connection re-activated"
        else
            echo "  ⚠️  Failed to re-activate connection"
        fi
    fi
    
    # Extra wait for bridge interfaces (VM networking may need more time)
    if [[ "$IFACE_TYPE" == "bridge" ]]; then
        echo "  ⏳ Bridge detected - waiting longer for VM networking..."
        sleep 10
    else
        echo "  ⏳ Waiting for network to stabilize..."
        sleep 5
    fi
}

# Trap to ensure restoration even if script is interrupted
trap restore_network EXIT

if [[ "$DIAGNOSE_ONLY" == "true" ]]; then
    echo "📌 Running diagnose only (no repairs)..."
    sudo $NETWORK_RECOVER diagnose
else
    echo "📌 Running repair (timeout: ${REPAIR_TIMEOUT}s)..."
    
    # ============================================================
    # CRITICAL: Set interface override for the repair
    # This ensures the repair targets the correct interface (br0)
    # even when the default route is missing after disabling it.
    # ============================================================
    export NETWORK_RECOVER_IFACE="$IFACE"
    
    # Run repair with timeout to prevent hanging on DNS repairs
    # -E preserves the environment variable through sudo
    timeout "$REPAIR_TIMEOUT" sudo -E $NETWORK_RECOVER repair
    REPAIR_EXIT=$?
    if [[ $REPAIR_EXIT -eq 124 ]]; then
        echo "  ⚠️  Repair timed out after ${REPAIR_TIMEOUT}s - forcing restoration"
    elif [[ $REPAIR_EXIT -ne 0 ]]; then
        echo "  ⚠️  Repair exited with code $REPAIR_EXIT"
    else
        echo "  ✅ Repair completed successfully"
    fi
fi

# Remove trap to avoid duplicate restoration
trap - EXIT

# Now explicitly restore
restore_network

# Verification
echo ""
echo "=============================================="
echo "  TEST RESULTS"
echo "=============================================="
echo ""

echo "📌 Final state:"
if ip link show "$IFACE" | grep -q "UP"; then
    echo "  ✅ Interface is UP"
else
    echo "  ❌ Interface is DOWN"
fi

FINAL_IP=$(ip -4 addr show "$IFACE" 2>/dev/null | grep -oP 'inet\s\K[0-9.]+' | head -1)
if [[ -n "$FINAL_IP" ]]; then
    echo "  ✅ IP: $FINAL_IP"
else
    echo "  ❌ No IP assigned"
fi

if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
    echo "  ✅ Internet reachable"
    INTERNET_OK=true
else
    echo "  ❌ Internet unreachable"
    INTERNET_OK=false
fi

# DNS check with fallback
if command -v nslookup &>/dev/null; then
    if nslookup google.com &>/dev/null 2>&1; then
        echo "  ✅ DNS working"
    else
        echo "  ❌ DNS not working"
    fi
elif command -v dig &>/dev/null; then
    if dig google.com +short &>/dev/null 2>&1; then
        echo "  ✅ DNS working"
    else
        echo "  ❌ DNS not working"
    fi
else
    echo "  ⚠️  nslookup/dig not available - skipping DNS test"
fi

echo ""
echo "=============================================="
echo "  TEST COMPLETE"
echo "=============================================="

if [[ "$INTERNET_OK" == "true" ]]; then
    echo "✅ Network recovery test PASSED"
    echo ""
    echo "  Run 'sudo $NETWORK_RECOVER status' to verify connectivity"
    exit 0
else
    echo "❌ Network recovery test FAILED"
    echo ""
    echo "  Manual recovery options:"
    echo "    sudo $NETWORK_RECOVER diagnose"
    echo "    sudo $NETWORK_RECOVER repair"
    echo "    sudo $NETWORK_RECOVER status"
    exit 1
fi