# Linux Network Recovery Tool

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.1-blue)](https://github.com/cypso05/Linux_Network-Recovery-Tool/releases)
[![Platform](https://img.shields.io/badge/platform-Linux-brightgreen)]()

A diagnostic and repair utility for Linux network connectivity issues. Designed to solve the "connected but cannot browse" problem without requiring a system reboot.

---

## What This Tool Does

When NetworkManager shows "Connected" but web pages won't load, this tool runs a structured series of checks — from the physical interface up through DNS resolution and HTTPS connectivity. If it finds a problem, it applies targeted repairs.

It wraps standard Linux networking commands (`ip`, `nmcli`, `ping`, `dig`, `dhclient`, `systemctl`) into a single diagnostic workflow, similar to how the Windows network troubleshooter operates.

---

## Installation

**From .deb package:**

```bash
sudo dpkg -i network-recover_1.1.1_all.deb
From source:

bash
git clone https://github.com/cypso05/Linux_Network-Recovery-Tool.git
cd Linux_Network-Recovery-Tool
sudo ./install.sh
The installer places the tool at /usr/local/bin/network-recover and optionally sets up an XFCE panel launcher.

Usage
bash
sudo network-recover status      # Quick health check
sudo network-recover diagnose    # Full diagnostic (no changes made)
sudo network-recover repair      # Diagnose and attempt repairs
sudo network-recover snapshot    # Save current network state
sudo network-recover watch       # Real-time monitoring
A GUI wrapper is available at /usr/local/bin/network-recover-gui with progress dialogs and desktop notifications.

Diagnostic Layers
The tool checks connectivity in sequence, from lowest to highest level:

Physical — carrier signal, operstate, link speed

Link — interface up/down, bridge membership, vnet attachment

IP — IPv4/IPv6 address presence, duplicate IP detection

Routing — default route, blackhole routes, metrics

Gateway — ARP entry, ICMP reachability

Internet — ping to multiple public IPs (ICMP + TCP fallback)

DNS — resolv.conf parsing, resolution tests, resolver responsiveness

HTTPS — curl-based connectivity tests, captive portal detection

NetworkManager — service status, device state, stale connections

Virtualization — libvirtd status, VM count

Kubernetes — cluster connectivity (optional, skipped if not configured)

Repairs
When run with repair, the tool applies fixes based on which layers failed:

Layer Failed	Repair Action
DNS	Flush caches (resolvectl, systemd-resolve), restart systemd-resolved
Gateway or Routing	Flush ARP cache
Physical or Link	Disconnect and reconnect interface via nmcli
IP	Renew DHCP lease or restart static IP connection
NetworkManager	Restart NetworkManager service
Bridge	Bring bridge up, re-enslave detached interfaces
Repairs are applied in dependency order. DNS is not repaired before the interface is confirmed up.

Example Output
text
==========================================
    NETWORK RECOVERY REPORT
==========================================
Interface: br0
Timestamp: 2026-06-24 14:05:21

Layer Results
==========================================
PASS Physical Link
PASS Interface State
PASS IP Address
PASS Gateway Reachable
PASS External IP Reachable
FAIL DNS Resolution
FAIL HTTPS Connectivity

Root Cause: DNS Resolution Failure

Applied Repair:
  - Flushed DNS cache
  - Restarted systemd-resolved
  - Retest: DNS Resolution PASS

Final Status: CONNECTED
==========================================
Reports and Logs
Every run generates a timestamped log:

text
/var/log/network-events/
  diagnostic-YYYY-MM-DD_HH-MM-SS.log
  recovery-YYYY-MM-DD_HH-MM-SS.log
  snapshot-YYYY-MM-DD_HH-MM-SS.log
Each report includes interface state, IP addresses, routing tables, DNS configuration, gateway tests, NetworkManager status, bridge status, and recent NetworkManager journal entries.

Snapshots are saved to /var/lib/network-recover/snapshots/.

Desktop Integration (XFCE)
A panel launcher can be added next to the network icon:

Right-click the panel, select Panel > Add New Items

Search for "Network Diagnose & Repair"

Click Add

Or run the automated setup:

bash
cd Linux_Network-Recovery-Tool
./integration/xfce-integration.sh
System Requirements
Requirement	Details
Distribution	Debian, Ubuntu, MX Linux, Fedora, RHEL, Arch, and derivatives
Init system	systemd
Network management	NetworkManager
Core dependencies	bash, iproute2, curl, nmcli, ping, grep, awk
Optional	zenity (GUI), libnotify (notifications), policykit-1 (pkexec)
Known Limitations
HTTPS tests may report failures when internet is working. This can occur due to firewall rules, proxy settings, or TLS interception. If layers 1-6 pass and you can browse normally, the HTTPS test result can be disregarded.

Bridge name may display as "None" in status output on some configurations. Bridge detection and repair functions are unaffected.

Root privileges are required. The tool modifies network interfaces, restarts services, and writes to system files. Review the source before running as root.

License
MIT License. See LICENSE for details.

Contributing
Issues and pull requests are welcome.

Fork the repository

Create a feature branch (git checkout -b feature/description)

Commit your changes

Push to the branch

Open a pull request