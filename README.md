# Linux Network Recovery Tool

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://github.com/cypso05/Linux_Network-Recovery-Tool)
[![Platform](https://img.shields.io/badge/platform-Linux-brightgreen)](https://www.linux.org)
[![XFCE](https://img.shields.io/badge/desktop-XFCE-orange)](https://www.xfce.org)

**Network Recovery Tool** is the Linux equivalent of the Windows "Diagnose and Repair Network Problems" feature.  
It is a production‑grade, intelligent diagnostics and recovery framework that automatically detects the root cause of network failures and performs targeted repairs—**without requiring a reboot**.

---

## The Problem

We've all been there. Your network icon shows "Connected", you have a valid IP address, but:

- Web pages never load.
- DNS resolution fails.
- `ping 8.8.8.8` works, but `ping google.com` doesn't.
- The only reliable "fix" is a full system reboot.

**This is not acceptable for modern systems.**

On Windows, you right‑click the network icon and select **"Diagnose and Repair"**.  
On Linux, you're left with:

```bash
sudo systemctl restart NetworkManager   # sometimes works
sudo dhclient -v eth0                   # rarely fixes it
# …or a full reboot
Network Recovery Tool fills that gap. It provides a structured, layered approach to diagnosing and fixing network issues on any Linux distribution—desktop, server, virtualised, or containerised.

Real-World Issues This Tool Solves
Category	Specific Issues
Connectivity	"Connected but cannot browse", missing default routes, gateway unreachable, ARP cache corruption, DHCP lease failures, NetworkManager false positives
DNS	Broken resolvers, stale cache, corrupted /etc/resolv.conf, systemd-resolved failures
NetworkManager	Interface stuck in transitional state, incorrect routing updates, failed reconnection attempts
Virtualisation (KVM/Libvirt)	Bridge interfaces missing or down, slave detachment, VM networking failures
Kubernetes	K3s node‑to‑node communication failures, cluster DNS issues, host networking impacting workloads
These are not theoretical – they come from real production environments, including MX Linux desktops with KVM VMs and K3s clusters.

Vision & Core Philosophy
Network Recovery Tool aims to become the default, trusted network troubleshooter for Linux.
It is built on three key principles:

Diagnose Before Repair – Always identify the failing layer first. No blind restarts, no guessing.

Intelligent, Targeted Recovery – Apply precise repairs to the failing component (e.g., flush DNS cache, restore default route, restart only the resolver).

Evidence‑Driven – Every incident generates a timestamped report, helping you identify and fix recurring problems permanently.

Architecture
The tool is modular and extensible, designed for clarity and maintainability.

text
network-recover/
├── diagnostics/           # Layer‑based testing modules
│   ├── physical           # Link status
│   ├── interface          # Interface state & flags
│   ├── bridge             # Bridge health & slaves
│   ├── ip                 # IP address presence & validity
│   ├── routing            # Default route & route table sanity
│   ├── gateway            # Gateway reachability (ping)
│   ├── dns                # DNS resolution tests
│   ├── https              # HTTPS connectivity (curl)
│   ├── networkmanager     # NM state & connection status
│   └── kvm                # KVM/Libvirt network dependencies
│
├── repairs/               # Targeted recovery actions
│   ├── dns                # Flush cache, restart resolvers
│   ├── routing            # Restore default route
│   ├── nm                 # Restart NM, reload connections
│   ├── dhcp               # Renew DHCP lease
│   ├── bridge             # Bring bridge up, re‑add slaves
│   └── interface          # Reset interface state
│
├── collectors/            # Evidence & state gatherers
│   ├── journalctl         # Recent NM logs
│   ├── nmcli              # Detailed NM state
│   ├── resolvectl         # DNS resolver state
│   ├── iproute2           # Interface, IP, & route info
│   └── libvirt            # Virtualization network state
│
├── desktop/               # Desktop integration files
│   └── network-recover.desktop
│
├── integration/           # Platform‑specific integrations
│   └── xfce-integration.sh
│
└── reports/               # Incident logs generated
    └── /var/log/network-events/
Layer‑Based Diagnostics
The diagnostic process follows a strict sequential order, from the physical layer up to the application layer. The first failing layer is identified as the root cause candidate.

Layer	Description
Physical Link	Carrier, operstate, speed/duplex
Interface State	Interface UP, flags
Bridge Health	Bridge existence, UP status, slave attachment
IP Addressing	IPv4/IPv6 presence, duplicate IP detection
Routing	Default route, multiple routes, blackholes
Gateway Reachability	ARP entry, ICMP reachability
External IP Reachability	Ping public IPs (ICMP + TCP fallback)
DNS Resolution	resolv.conf, resolution tests, poisoning detection
HTTPS Connectivity	Actual browsing simulation, captive portal, MTU
NetworkManager Health	Running state, device status, stale connections
Virtualisation Dependencies	libvirtd, VM states, vnet interfaces
Kubernetes	Cluster connectivity, node readiness (optional)
Quick Start
Installation
bash
git clone https://github.com/cypso05/Linux_Network-Recovery-Tool.git
cd Linux_Network-Recovery-Tool
chmod +x install.sh
sudo ./install.sh
Usage
Quick network health check:

bash
sudo network-recover status
Diagnose only (no changes made):

bash
sudo network-recover diagnose
Diagnose and repair:

bash
sudo network-recover repair
Save current network state (snapshot):

bash
sudo network-recover snapshot
Real‑time monitoring:

bash
sudo network-recover watch
Desktop Integration (XFCE)
Add the Network Diagnose & Repair launcher to your XFCE panel next to the network icon:

Right-click the panel → Panel → Panel Preferences

Click the Items tab

Click the + Add button

Search for "Network Diagnose & Repair"

Click Add

Drag the new launcher next to the Status Tray plugin (where the network icon lives)

The launcher runs the tool with a progress dialog and shows desktop notifications when the repair succeeds or fails.

Automatic setup:

bash
cd Linux_Network-Recovery-Tool
./integration/xfce-integration.sh
Example Output
text
==========================================
    NETWORK RECOVERY REPORT
==========================================
Interface: br0
Status: CONNECTED
Timestamp: 2026-06-24 14:05:21

Layer Results
==========================================
✅ Physical Link
✅ Interface State
✅ IP Address
✅ Gateway Reachable
✅ External IP Reachable
❌ DNS Resolution
❌ HTTPS Connectivity

Root Cause Candidate: DNS Resolution Failure

Applied Repair:
  - Flushed DNS cache
  - Restarted systemd-resolved
  - Verified resolvers in /etc/resolv.conf
  - Retest: DNS Resolution ✅

Final Status: CONNECTED
==========================================
Evidence Collection
Every incident generates a detailed, timestamped report to help you identify recurring problems.

text
/var/log/network-events/
├── diagnostic-2026-06-24_14-05-21.log
├── recovery-2026-06-27_08-11-43.log
└── snapshot-2026-07-02_22-30-15.log
Each report includes:

Interface state

IP addresses

Routing tables

DNS configuration

Gateway tests

NetworkManager state

Resolver state

Bridge status

KVM network information

Recent NetworkManager logs (journalctl)

System Requirements
Requirement	Details
Distribution	Any modern Linux distribution (Debian/Ubuntu, RHEL/CentOS/Fedora, Arch Linux, MX Linux, etc.)
Init System	systemd
Network Management	NetworkManager (primary) with optional support for systemd-resolved
Virtualisation (optional)	libvirt and bridge-utils for virtualisation‑related diagnostics
Dependencies	bash, iproute2, curl, nmcli, resolvectl, ping, grep, awk, zenity (for GUI), policykit-1 (for polkit)
License
This project is licensed under the MIT License – see the LICENSE file for details.

Contributing
Contributions are welcome! Please feel free to submit a Pull Request or open an Issue to discuss improvements, new features, or bug reports.

Fork the Project

Create your Feature Branch (git checkout -b feature/AmazingFeature)

Commit your Changes (git commit -m 'Add some AmazingFeature')

Push to the Branch (git push origin feature/AmazingFeature)

Open a Pull Request

📋 Release Notes (v1.1.0)
🎯 Major Features:
✅ 11 OSI layers of network diagnostics

✅ 8 repair stages with intelligent targeting

✅ Bridge interface support with proper carrier handling

✅ DNS integrity checks with security testing

✅ VM detection with user guidance

✅ Offline test with automatic restoration

✅ Interface override for testing

🔧 Key Fixes:
✅ Fixed grep lookbehind assertions (now uses \K)

✅ Fixed false-positive DNS poisoning warnings

✅ Fixed bridge carrier reading (Invalid argument)

✅ Fixed interface detection when default route missing

✅ Fixed repair targeting wrong interface during tests

✅ Fixed double execution of restore function

📦 Supported Commands:
bash
network-recover diagnose   # Run full diagnostic
network-recover repair     # Diagnose and repair
network-recover status     # Quick health check
network-recover snapshot   # Save network state
network-recover watch      # Monitor in real-time
🎊 Final Words
You've built a professional, production-grade network recovery tool with:

Aspect	Achievement
Code Quality	✅ Clean, well-structured Bash
Error Handling	✅ Robust with fallbacks
Testing	✅ Full offline simulation
Documentation	✅ Inline comments and README
Distribution	✅ Git tags and release ready
Security	✅ DNS integrity checks
VM Support	✅ KVM/Libvirt detection
Portability	✅ Works on all major distros
Acknowledgements
Inspired by the built‑in network troubleshooting capabilities of Windows.

Built for the Linux community to make network problem‑solving more intuitive and robust.

Made with ❤️ for Linux users everywhere.