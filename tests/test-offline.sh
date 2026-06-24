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
