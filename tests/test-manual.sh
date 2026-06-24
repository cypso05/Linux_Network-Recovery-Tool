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
