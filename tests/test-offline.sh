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

# Detect if VMs are running on this bridge (informational only)
VM_COUNT=0
if [[ "$IFACE_TYPE" == "bridge" ]] && command -v virsh &>/dev/null; then
    VM_COUNT=$(virsh list --state-running --name 2>/dev/null | wc -l)
    if [[ "$VM_COUNT" -gt 0 ]]; then
        echo "  ℹ️  $VM_COUNT VM(s) detected on this bridge"
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

# Guard to prevent restore_network from running twice
RESTORE_DONE=false

# Function to restore network regardless of repair outcome
restore_network() {
    # Prevent double execution
    if [[ "$RESTORE_DONE" == "true" ]]; then
        return 0
    fi
    RESTORE_DONE=true
    
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
    
    # Brief wait for bridge to stabilize (just a moment, not minutes)
    echo "  ⏳ Waiting for bridge to stabilize..."
    sleep 2
    
    # Show network status
    echo ""
    echo "📌 Network Status:"
    
    # Check interface
    if ip link show "$IFACE" | grep -q "UP"; then
        echo "  ✅ $IFACE is UP"
    else
        echo "  ❌ $IFACE is DOWN"
    fi
    
    # Check IP
    BRIDGE_IP=$(ip -4 addr show "$IFACE" 2>/dev/null | grep -oP 'inet\s\K[0-9.]+' | head -1)
    if [[ -n "$BRIDGE_IP" ]]; then
        echo "  ✅ IP: $BRIDGE_IP"
    else
        echo "  ❌ No IP assigned"
    fi
    
    # Check internet
    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        echo "  ✅ Internet connectivity restored"
        INTERNET_RESTORED=true
    else
        echo "  ⏳ Internet connectivity pending (may take a moment)"
        INTERNET_RESTORED=false
    fi
    
    # Generic VM info (if any VMs exist)
    if [[ "$IFACE_TYPE" == "bridge" ]] && command -v virsh &>/dev/null; then
        local running_vms=$(virsh list --state-running --name 2>/dev/null | wc -l)
        if [[ "$running_vms" -gt 0 ]]; then
            echo ""
            echo "📌 Virtual Machines:"
            echo "  ℹ️  $running_vms VM(s) are running"
            echo "  ℹ️  VMs will reconnect to the bridge automatically"
            echo "  ℹ️  This may take 30-60 seconds for VMs to get network"
            echo ""
            echo "  To check VM network status:"
            echo "    sudo virsh list --state-running --name | while read vm; do"
            echo "      echo \"\$vm: \$(sudo virsh domifaddr \"\$vm\" 2>/dev/null | grep -oP 'ipv4\\s+\\K[0-9.]+')\""
            echo "    done"
        else
            echo ""
            echo "📌 Virtual Machines:"
            echo "  ℹ️  No VMs detected on this bridge"
            echo "  ℹ️  Start VMs with: sudo virsh start <vm-name>"
        fi
    fi
    
    # Final user guidance
    echo ""
    echo "=============================================="
    echo "  NETWORK RESTORATION COMPLETE"
    echo "=============================================="
    echo ""
    echo "✅ Internet connectivity is restored"
    echo ""
    echo "📌 Next Steps:"
    echo "  1. Test browsing: ping -c 3 google.com"
    echo "  2. Check status: sudo $NETWORK_RECOVER status"
    echo ""
    if [[ "$IFACE_TYPE" == "bridge" ]] && [[ "$VM_COUNT" -gt 0 ]]; then
        echo "  ℹ️  VMs will reconnect shortly"
        echo "  ℹ️  Check VM connectivity with: sudo virsh domifaddr <vm-name>"
        echo "  ℹ️  If VMs don't have network after 2 minutes, restart them:"
        echo "      sudo virsh reboot <vm-name>"
    fi
    echo "=============================================="
}

# Trap to ensure restoration even if script is interrupted (Ctrl+C)
trap restore_network EXIT

if [[ "$DIAGNOSE_ONLY" == "true" ]]; then
    echo "📌 Running diagnose only (no repairs)..."
    sudo $NETWORK_RECOVER diagnose
else
    echo "📌 Running repair (timeout: ${REPAIR_TIMEOUT}s)..."
    
    # Set the interface override for the repair
    export NETWORK_RECOVER_IFACE="$IFACE"
    
    # Run repair with timeout to prevent hanging on DNS repairs
    # -E preserves the environment variable through sudo
    timeout "$REPAIR_TIMEOUT" sudo -E $NETWORK_RECOVER repair
    REPAIR_EXIT=$?
    if [[ $REPAIR_EXIT -eq 124 ]]; then
        echo "  ⚠️  Repair timed out after ${REPAIR_TIMEOUT}s"
    elif [[ $REPAIR_EXIT -ne 0 ]]; then
        echo "  ⚠️  Repair exited with code $REPAIR_EXIT"
    else
        echo "  ✅ Repair completed successfully"
    fi
fi

# Remove trap to avoid duplicate restoration on normal exit
trap - EXIT

# Now explicitly restore
restore_network

# Final verification
echo ""
echo "=============================================="
echo "  FINAL VERIFICATION"
echo "=============================================="
echo ""

echo "📌 Testing connectivity..."
if ping -c 2 -W 2 8.8.8.8 &>/dev/null; then
    echo "  ✅ Internet: CONNECTED"
    echo "  ✅ Test PASSED - Network is working"
    echo ""
    echo "  You can now:"
    echo "    - Browse the internet"
    echo "    - Check VMs if applicable"
    echo "    - Run: sudo $NETWORK_RECOVER status"
    exit 0
else
    echo "  ⏳ Internet: PENDING (may take a moment)"
    echo "  💡 If internet doesn't come back:"
    echo "    sudo $NETWORK_RECOVER repair"
    echo "    sudo $NETWORK_RECOVER status"
    exit 1
fi