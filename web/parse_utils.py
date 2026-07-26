#!/usr/bin/env python3
"""
Network Recovery - Output Parser Module
Parses collector and diagnostic script outputs into structured data.
All emojis and human-readable text → machine-readable JSON.
"""

import re
import json
import subprocess
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


class Status(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    INFO = "info"
    UNKNOWN = "unknown"


@dataclass
class DiagnosticResult:
    """Single diagnostic check result"""
    layer: str
    status: Status
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""


@dataclass
class NetworkInterface:
    """Parsed network interface data"""
    name: str
    type: str  # ethernet, wireless, bridge, bond, virtual
    mac: str = ""
    mtu: int = 1500
    state: str = "unknown"  # up, down, dormant
    carrier: bool = False
    operstate: str = "unknown"
    flags: str = ""
    ipv4: str = ""
    ipv6: str = ""
    speed: str = ""
    duplex: str = ""
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0
    collisions: int = 0
    # Wireless specific
    ssid: str = ""
    signal_dbm: int = 0
    frequency: str = ""
    # Bridge specific
    slaves: List[str] = field(default_factory=list)


@dataclass
class VMData:
    """Parsed VM information"""
    name: str
    state: str = "unknown"  # running, shutoff, paused
    vcpus: int = 0
    memory_current: str = ""
    memory_max: str = ""
    ip: str = ""
    mac: str = ""
    disks: List[Dict] = field(default_factory=list)
    interfaces: List[Dict] = field(default_factory=list)
    # SSH-collected metrics
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    disk_percent: float = 0.0
    swap_percent: float = 0.0
    load_1m: float = 0.0
    load_5m: float = 0.0
    load_15m: float = 0.0
    pods_count: int = 0


@dataclass
class NetworkManagerStatus:
    """NetworkManager status data"""
    running: bool = False
    state: str = "unknown"
    devices: List[Dict] = field(default_factory=list)
    connections: List[Dict] = field(default_factory=list)
    active_connections: List[str] = field(default_factory=list)


@dataclass
class DNSConfig:
    """DNS configuration data"""
    servers: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    dnssec: str = "unknown"
    resolv_conf: str = ""


class OutputParser:
    """
    Parses output from network-recover collectors and diagnostics.
    Handles emoji-based status indicators and produces structured data.
    """
    
    # Emoji patterns for status detection
    STATUS_PATTERNS = {
        Status.PASS: ['✅', 'PASS', '✓', '✔'],
        Status.FAIL: ['❌', 'FAIL', '✗', '✘'],
        Status.WARN: ['⚠️', '⚠', 'WARN', '⚡'],
        Status.INFO: ['ℹ️', 'ℹ', 'INFO', '📌', '📊', '📝'],
    }
    
    @staticmethod
    def detect_status(line: str) -> Tuple[Status, str]:
        """Extract status and clean message from a line"""
        for status, patterns in OutputParser.STATUS_PATTERNS.items():
            for pattern in patterns:
                if pattern in line:
                    # Remove the emoji/pattern and clean up
                    message = line.replace(pattern, '').strip()
                    message = re.sub(r'\s+', ' ', message)
                    return status, message
        return Status.UNKNOWN, line.strip()
    
    @staticmethod
    def parse_sysfs_value(path: str, default: Any = None) -> Any:
        """Read a value from /sys filesystem"""
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError):
            return default
    
    # ============================================================
    # COLLECTOR PARSERS
    # ============================================================
    
    @staticmethod
    def parse_iproute2(output: str) -> Dict[str, Any]:
        """Parse iproute2 collector output"""
        result = {
            "interfaces": [],
            "routes": [],
            "neighbors": [],
            "bridges": []
        }
        
        current_section = None
        current_iface = None
        
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Section headers
            if line.startswith('==='):
                section = line.strip('= ').lower()
                if 'ip addr' in section:
                    current_section = 'interfaces'
                elif 'ip route' in section:
                    current_section = 'routes'
                elif 'ip neigh' in section:
                    current_section = 'neighbors'
                elif 'bridge link' in section:
                    current_section = 'bridges'
                continue
            
            if current_section == 'interfaces':
                # Parse interface lines
                iface_match = re.match(r'^\d+:\s+(\S+):\s+<(.+?)>', line)
                if iface_match:
                    if current_iface:
                        result["interfaces"].append(current_iface)
                    current_iface = {
                        "name": iface_match.group(1),
                        "flags": iface_match.group(2).split(','),
                        "addresses": []
                    }
                elif current_iface and 'inet' in line:
                    addr_match = re.search(r'inet\s+(\S+)', line)
                    if addr_match:
                        current_iface["addresses"].append(addr_match.group(1))
            
            elif current_section == 'routes':
                if 'default' in line or 'via' in line:
                    result["routes"].append(line)
            
            elif current_section == 'neighbors':
                if line and 'dev' in line:
                    result["neighbors"].append(line)
            
            elif current_section == 'bridges':
                if line and ':' in line:
                    result["bridges"].append(line)
        
        if current_iface:
            result["interfaces"].append(current_iface)
        
        return result
    
    @staticmethod
    def parse_nmcli(output: str) -> NetworkManagerStatus:
        """Parse nmcli collector output"""
        nm_status = NetworkManagerStatus()
        current_section = None
        
        for line in output.split('\n'):
            line = line.strip()
            if not line or line.startswith('==='):
                if 'general status' in line.lower():
                    current_section = 'general'
                elif 'device status' in line.lower():
                    current_section = 'devices'
                elif 'active connections' in line.lower():
                    current_section = 'connections'
                continue
            
            if current_section == 'general':
                # Parse: STATE      CONNECTIVITY  WIFI-HW  WIFI     WWAN-HW  WWAN    
                parts = line.split()
                if len(parts) >= 2 and parts[0] not in ['STATE', '---']:
                    nm_status.state = parts[0]
                    nm_status.running = parts[0] in ['connected', 'connecting']
            
            elif current_section == 'devices':
                # Parse: DEVICE  TYPE      STATE      CONNECTION
                parts = line.split()
                if len(parts) >= 3 and parts[0] not in ['DEVICE', '---']:
                    nm_status.devices.append({
                        "device": parts[0],
                        "type": parts[1] if len(parts) > 1 else "",
                        "state": parts[2] if len(parts) > 2 else "",
                        "connection": ' '.join(parts[3:]) if len(parts) > 3 else ""
                    })
            
            elif current_section == 'connections':
                parts = line.split()
                if len(parts) >= 1 and parts[0] not in ['NAME', '---']:
                    nm_status.active_connections.append(parts[0])
        
        return nm_status
    
    @staticmethod
    def parse_libvirt(output: str) -> List[VMData]:
        """Parse libvirt collector output (virsh list)"""
        vms = []
        current_section = None
        current_vm = None
        
        for line in output.split('\n'):
            line = line.strip()
            if not line or line.startswith('==='):
                if 'virsh list' in line.lower():
                    current_section = 'vms'
                elif 'virsh net-list' in line.lower():
                    current_section = 'networks'
                continue
            
            if current_section == 'vms':
                # Skip headers and separators
                if 'Id' in line and 'Name' in line:
                    continue
                if '---' in line:
                    continue
                if 'not installed' in line.lower():
                    continue
                
                # Parse:  Id    Name                           State
                #         -------------------------------------
                #         1     vm-name                        running
                parts = line.split()
                if len(parts) >= 3:
                    vm_id = parts[0]
                    vm_name = parts[1]
                    vm_state = parts[-1] if parts[-1] in ['running', 'shut', 'paused', 'shutoff'] else parts[-1]
                    
                    vm = VMData(
                        name=vm_name,
                        state=vm_state
                    )
                    vms.append(vm)
        
        return vms
    
    @staticmethod
    def parse_resolvectl(output: str) -> DNSConfig:
        """Parse resolvectl collector output"""
        dns = DNSConfig()
        
        lines = output.split('\n')
        in_resolv_conf = False
        resolv_lines = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            if '=== /etc/resolv.conf ===' in line:
                in_resolv_conf = True
                continue
            
            if in_resolv_conf:
                resolv_lines.append(line)
                continue
            
            # Parse DNS servers
            if 'DNS Servers:' in line or 'Current DNS Server:' in line:
                server = line.split(':', 1)[1].strip()
                if server and server not in dns.servers:
                    dns.servers.append(server)
            
            # Parse domains
            if 'DNS Domain:' in line or 'Domains:' in line:
                domain = line.split(':', 1)[1].strip()
                if domain and domain not in dns.domains:
                    dns.domains.append(domain)
            
            # Parse DNSSEC
            if 'DNSSEC' in line:
                if 'yes' in line.lower() or 'supported' in line.lower():
                    dns.dnssec = 'enabled'
                elif 'no' in line.lower():
                    dns.dnssec = 'disabled'
        
        dns.resolv_conf = '\n'.join(resolv_lines)
        
        # Extract nameservers from resolv.conf
        for line in resolv_lines:
            if line.startswith('nameserver'):
                ns = line.split()[1] if len(line.split()) > 1 else ''
                if ns and ns not in dns.servers:
                    dns.servers.append(ns)
        
        return dns
    
    @staticmethod
    def parse_journalctl(output: str) -> List[Dict]:
        """Parse journalctl collector output"""
        entries = []
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('===') or 'no networkmanager logs' in line.lower():
                continue
            
            # Parse journalctl line format: MMM DD HH:MM:SS hostname NetworkManager[PID]: message
            timestamp_match = re.match(r'^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})', line)
            if timestamp_match:
                timestamp = timestamp_match.group(1)
                rest = line[timestamp_match.end():].strip()
                
                # Extract process
                proc_match = re.match(r'(\S+)\s+NetworkManager\[(\d+)\]:\s+(.*)', rest)
                if proc_match:
                    entries.append({
                        "timestamp": timestamp,
                        "host": proc_match.group(1),
                        "pid": proc_match.group(2),
                        "message": proc_match.group(3)
                    })
                else:
                    entries.append({
                        "timestamp": timestamp,
                        "message": rest
                    })
        
        return entries
    
    # ============================================================
    # DIAGNOSTIC PARSERS
    # ============================================================
    
    @staticmethod
    def parse_physical_diagnostic(output: str) -> DiagnosticResult:
        """Parse physical layer diagnostic output"""
        result = DiagnosticResult(
            layer="physical",
            status=Status.PASS,
            message="Physical layer OK"
        )
        
        details = {
            "carrier": None,
            "operstate": None,
            "interface_type": None,
            "speed": None,
            "duplex": None,
            "link_detected": None,
            "signal_dbm": None,
            "signal_quality": None,
            "errors": {"rx": 0, "tx": 0}
        }
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "Carrier:" in message or "Carrier" in line:
                if "present" in message or "LOST" in message:
                    details["carrier"] = "present" not in message.lower()
                    if "LOST" in message:
                        result.status = Status.FAIL
                        result.message = "Carrier lost - check cable"
            
            elif "State:" in message:
                details["operstate"] = message.split(":", 1)[1].strip() if ":" in message else message
            
            elif "Type:" in message:
                details["interface_type"] = message.split(":", 1)[1].strip() if ":" in message else message
            
            elif "Speed:" in message:
                details["speed"] = message.split(":", 1)[1].strip() if ":" in message else message
            
            elif "Duplex:" in message:
                details["duplex"] = message.split(":", 1)[1].strip() if ":" in message else message
            
            elif "Link detected:" in message:
                detected = message.split(":", 1)[1].strip().lower() if ":" in message else ""
                details["link_detected"] = detected == "yes"
            
            elif "Signal:" in message:
                match = re.search(r'(-?\d+)\s*dBm', message)
                if match:
                    details["signal_dbm"] = int(match.group(1))
            
            elif "Quality:" in message:
                details["signal_quality"] = message.split(":", 1)[1].strip() if ":" in message else message
            
            elif "Errors:" in message:
                match = re.search(r'RX=(\d+),\s*TX=(\d+)', message)
                if match:
                    details["errors"]["rx"] = int(match.group(1))
                    details["errors"]["tx"] = int(match.group(2))
        
        result.details = details
        return result
    
    @staticmethod
    def parse_interface_diagnostic(output: str) -> DiagnosticResult:
        """Parse interface layer diagnostic output"""
        result = DiagnosticResult(
            layer="interface",
            status=Status.PASS,
            message="Interface layer OK"
        )
        
        details = {
            "name": None,
            "type": None,
            "mac": None,
            "mtu": None,
            "flags": None,
            "operstate": None,
            "carrier": None,
            "speed": None,
            "duplex": None,
            "errors": {"rx": 0, "tx": 0},
            "dropped": {"rx": 0, "tx": 0},
            "collisions": 0
        }
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "Interface:" in line:
                details["name"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "Type:" in line:
                details["type"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "MAC:" in line:
                details["mac"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "MTU:" in line:
                try:
                    details["mtu"] = int(line.split(":", 1)[1].strip())
                except:
                    pass
            
            elif "Flags:" in line:
                details["flags"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "State:" in line:
                details["operstate"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "Carrier:" in message:
                details["carrier"] = "present" in message.lower()
                if "LOST" in message:
                    result.status = Status.FAIL
            
            elif "Speed:" in line:
                details["speed"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "Duplex:" in line:
                details["duplex"] = line.split(":", 1)[1].strip() if ":" in line else ""
            
            elif "Interface state:" in message:
                state = message.split(":", 1)[1].strip() if ":" in message else ""
                if state != "up":
                    result.status = Status.WARN if state == "dormant" else Status.FAIL
            
            elif "Interface flags:" in message:
                if "DOWN" in message:
                    result.status = Status.FAIL
            
            elif "Errors:" in message:
                match = re.search(r'RX=(\d+),\s*TX=(\d+)', message)
                if match:
                    details["errors"]["rx"] = int(match.group(1))
                    details["errors"]["tx"] = int(match.group(2))
            
            elif "Dropped:" in message:
                match = re.search(r'RX=(\d+),\s*TX=(\d+)', message)
                if match:
                    details["dropped"]["rx"] = int(match.group(1))
                    details["dropped"]["tx"] = int(match.group(2))
            
            elif "Collisions:" in message:
                try:
                    details["collisions"] = int(message.split(":")[1].strip())
                except:
                    pass
        
        result.details = details
        return result
    
    @staticmethod
    def parse_ip_diagnostic(output: str) -> DiagnosticResult:
        """Parse IP layer diagnostic output"""
        result = DiagnosticResult(
            layer="ip",
            status=Status.PASS,
            message="IP configuration OK"
        )
        
        details = {"ipv4": None, "interface": None}
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "IPv4:" in message:
                details["ipv4"] = message.split(":", 1)[1].strip() if ":" in message else ""
                if status == Status.FAIL:
                    result.status = Status.FAIL
                    result.message = "No IPv4 address configured"
            elif "No IPv4" in message:
                result.status = Status.FAIL
                result.message = "No IPv4 address configured"
        
        result.details = details
        return result
    
    @staticmethod
    def parse_routing_diagnostic(output: str) -> DiagnosticResult:
        """Parse routing diagnostic output"""
        result = DiagnosticResult(
            layer="routing",
            status=Status.PASS,
            message="Routing OK"
        )
        
        details = {"default_gateway": None}
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "Default gateway:" in message:
                details["default_gateway"] = message.split(":", 1)[1].strip() if ":" in message else ""
            elif "No default route" in message:
                result.status = Status.FAIL
                result.message = "No default route found"
        
        result.details = details
        return result
    
    @staticmethod
    def parse_gateway_diagnostic(output: str) -> DiagnosticResult:
        """Parse gateway diagnostic output"""
        result = DiagnosticResult(
            layer="gateway",
            status=Status.PASS,
            message="Gateway reachable"
        )
        
        details = {"gateway": None, "reachable": False}
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "Gateway" in message and "reachable" in message:
                # Extract gateway IP
                match = re.search(r'Gateway\s+([\d.]+)\s+reachable', message)
                if match:
                    details["gateway"] = match.group(1)
                    details["reachable"] = True
            elif "Gateway" in message and "unreachable" in message:
                match = re.search(r'Gateway\s+([\d.]+)\s+unreachable', message)
                if match:
                    details["gateway"] = match.group(1)
                details["reachable"] = False
                result.status = Status.FAIL
                result.message = "Gateway unreachable"
            elif "No gateway" in message:
                result.status = Status.FAIL
                result.message = "No gateway configured"
        
        result.details = details
        return result
    
    @staticmethod
    def parse_dns_diagnostic(output: str) -> DiagnosticResult:
        """Parse DNS diagnostic output"""
        result = DiagnosticResult(
            layer="dns",
            status=Status.PASS,
            message="DNS resolution OK"
        )
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "DNS resolution works" in message:
                pass  # Already PASS
            elif "DNS resolution failed" in message:
                result.status = Status.FAIL
                result.message = "DNS resolution failed"
        
        return result
    
    @staticmethod
    def parse_https_diagnostic(output: str) -> DiagnosticResult:
        """Parse HTTPS diagnostic output"""
        result = DiagnosticResult(
            layer="https",
            status=Status.PASS,
            message="HTTPS connectivity OK"
        )
        
        details = {
            "tests": [],
            "captive_portal_detected": False,
            "success_count": 0,
            "total_count": 0
        }
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "HTTPS:" in message:
                # Parse URL and HTTP code
                match = re.search(r'HTTPS:\s+(\S+)\s+\(HTTP\s+(\d+)\)', message)
                if match:
                    test_result = {
                        "url": match.group(1),
                        "http_code": int(match.group(2)),
                        "status": "pass" if status == Status.PASS else "fail"
                    }
                    details["tests"].append(test_result)
                    if status == Status.PASS:
                        details["success_count"] += 1
                    details["total_count"] += 1
            
            elif "captive portal" in message.lower():
                if "Possible captive portal" in message or "detected" in message:
                    details["captive_portal_detected"] = True
                    result.status = Status.WARN
                    result.message = "Possible captive portal detected"
            
            elif "HTTPS connectivity OK" in message:
                pass  # Already handled
            elif "HTTPS connectivity FAILED" in message:
                result.status = Status.FAIL
                result.message = "HTTPS connectivity failed"
        
        result.details = details
        return result
    
    @staticmethod
    def parse_bridge_diagnostic(output: str) -> DiagnosticResult:
        """Parse bridge diagnostic output"""
        result = DiagnosticResult(
            layer="bridge",
            status=Status.PASS,
            message="Bridge configuration OK"
        )
        
        details = {"bridge": None, "up": False, "slaves": []}
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "No bridge configured" in message:
                result.status = Status.INFO
                result.message = "No bridge configured"
            
            elif "Bridge" in message and "is UP" in message:
                match = re.search(r'Bridge\s+(\S+)\s+is UP', message)
                if match:
                    details["bridge"] = match.group(1)
                    details["up"] = True
            
            elif "Bridge" in message and "is DOWN" in message:
                match = re.search(r'Bridge\s+(\S+)\s+is DOWN', message)
                if match:
                    details["bridge"] = match.group(1)
                result.status = Status.FAIL
                result.message = "Bridge is DOWN"
            
            elif "enslaved to" in message:
                match = re.search(r'(\S+)\s+enslaved', message)
                if match:
                    details["slaves"].append(match.group(1))
            
            elif "NOT enslaved" in message:
                result.status = Status.FAIL
                result.message = "Interface not enslaved to bridge"
        
        result.details = details
        return result
    
    @staticmethod
    def parse_networkmanager_diagnostic(output: str) -> DiagnosticResult:
        """Parse NetworkManager diagnostic output"""
        result = DiagnosticResult(
            layer="networkmanager",
            status=Status.PASS,
            message="NetworkManager running"
        )
        
        details = {"running": False, "state": None}
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "NetworkManager is running" in message:
                details["running"] = True
                match = re.search(r'state:\s*(\S+)', message)
                if match:
                    details["state"] = match.group(1)
            
            elif "NetworkManager is NOT running" in message:
                result.status = Status.FAIL
                result.message = "NetworkManager not running"
            
            elif "NetworkManager not installed" in message:
                result.status = Status.INFO
                result.message = "NetworkManager not installed"
        
        result.details = details
        return result
    
    @staticmethod
    def parse_kvm_diagnostic(output: str) -> DiagnosticResult:
        """Parse KVM/libvirt diagnostic output"""
        result = DiagnosticResult(
            layer="kvm",
            status=Status.PASS,
            message="KVM/libvirt OK"
        )
        
        details = {"running": False, "running_vms": 0, "total_vms": 0}
        
        for line in output.split('\n'):
            line = line.strip()
            status, message = OutputParser.detect_status(line)
            
            if "libvirtd running" in message:
                details["running"] = True
                # Extract VM counts: "X/Y VMs active"
                match = re.search(r'(\d+)/(\d+)\s+VMs', message)
                if match:
                    details["running_vms"] = int(match.group(1))
                    details["total_vms"] = int(match.group(2))
            
            elif "libvirtd not running" in message:
                result.status = Status.FAIL
                result.message = "libvirtd not running"
            
            elif "libvirt not installed" in message:
                result.status = Status.INFO
                result.message = "libvirt not installed"
        
        result.details = details
        return result
    
    # ============================================================
    # FULL DIAGNOSTIC RUNNER
    # ============================================================
    
    @staticmethod
    def run_all_diagnostics(
        diagnostics_dir: str,
        interface: str = None,
        bridge: str = None
    ) -> List[DiagnosticResult]:
        """Run all diagnostic layers and return structured results"""
        
        results = []
        
        # Layer 1: Physical
        cmd = [f"{diagnostics_dir}/physical"]
        if interface:
            cmd.append(interface)
        output = subprocess.run(cmd, capture_output=True, text=True).stdout
        results.append(OutputParser.parse_physical_diagnostic(output))
        
        # Layer 2: Interface
        cmd = [f"{diagnostics_dir}/interface"]
        if interface:
            cmd.append(interface)
        output = subprocess.run(cmd, capture_output=True, text=True).stdout
        results.append(OutputParser.parse_interface_diagnostic(output))
        
        # Layer 3: IP
        cmd = [f"{diagnostics_dir}/ip"]
        if interface:
            cmd.append(interface)
        output = subprocess.run(cmd, capture_output=True, text=True).stdout
        results.append(OutputParser.parse_ip_diagnostic(output))
        
        # Layer 4: Routing
        output = subprocess.run(
            [f"{diagnostics_dir}/routing"], 
            capture_output=True, text=True
        ).stdout
        results.append(OutputParser.parse_routing_diagnostic(output))
        
        # Layer 5: Gateway
        output = subprocess.run(
            [f"{diagnostics_dir}/gateway"], 
            capture_output=True, text=True
        ).stdout
        results.append(OutputParser.parse_gateway_diagnostic(output))
        
        # Layer 6: DNS
        output = subprocess.run(
            [f"{diagnostics_dir}/dns"], 
            capture_output=True, text=True
        ).stdout
        results.append(OutputParser.parse_dns_diagnostic(output))
        
        # Layer 7: HTTPS
        output = subprocess.run(
            [f"{diagnostics_dir}/https"], 
            capture_output=True, text=True
        ).stdout
        results.append(OutputParser.parse_https_diagnostic(output))
        
        # Layer 8: NetworkManager
        output = subprocess.run(
            [f"{diagnostics_dir}/networkmanager"], 
            capture_output=True, text=True
        ).stdout
        results.append(OutputParser.parse_networkmanager_diagnostic(output))
        
        # Layer 9: Bridge
        cmd = [f"{diagnostics_dir}/bridge"]
        if bridge:
            cmd.append(bridge)
        if interface:
            cmd.append(interface)
        output = subprocess.run(cmd, capture_output=True, text=True).stdout
        results.append(OutputParser.parse_bridge_diagnostic(output))
        
        # Layer 10: KVM
        output = subprocess.run(
            [f"{diagnostics_dir}/kvm"], 
            capture_output=True, text=True
        ).stdout
        results.append(OutputParser.parse_kvm_diagnostic(output))
        
        return results
    
    @staticmethod
    def run_collector(collectors_dir: str, name: str, *args) -> Dict[str, Any]:
        """Run a collector and return parsed results"""
        script_path = f"{collectors_dir}/{name}"
        result = subprocess.run(
            [script_path] + list(args),
            capture_output=True,
            text=True
        )
        
        output = result.stdout
        
        # Route to appropriate parser
        parsers = {
            'iproute2': OutputParser.parse_iproute2,
            'nmcli': OutputParser.parse_nmcli,
            'libvirt': OutputParser.parse_libvirt,
            'resolvectl': OutputParser.parse_resolvectl,
            'journalctl': OutputParser.parse_journalctl,
        }
        
        if name in parsers:
            parsed = parsers[name](output)
            if hasattr(parsed, '__dataclass_fields__'):
                return asdict(parsed)
            return parsed
        
        return {"raw": output}
    
    @staticmethod
    def diagnostics_to_json(results: List[DiagnosticResult]) -> Dict:
        """Convert diagnostic results to JSON-serializable dict"""
        output = {
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r.status == Status.PASS),
                "fail": sum(1 for r in results if r.status == Status.FAIL),
                "warn": sum(1 for r in results if r.status == Status.WARN),
                "info": sum(1 for r in results if r.status == Status.INFO),
                "overall_status": "pass"
            },
            "layers": []
        }
        
        # Determine overall status
        if output["summary"]["fail"] > 0:
            output["summary"]["overall_status"] = "fail"
        elif output["summary"]["warn"] > 0:
            output["summary"]["overall_status"] = "warn"
        
        for result in results:
            output["layers"].append({
                "layer": result.layer,
                "status": result.status.value,
                "message": result.message,
                "details": result.details
            })
        
        return output


# ============================================================
# UTILITY: SSH VM Metrics (from network-recover-dashboard)
# ============================================================

def collect_vm_metrics_ssh(vm_ip: str, ssh_user: str = "root") -> Dict[str, Any]:
    """
    Collect VM metrics via SSH (replicates network-recover-dashboard functionality)
    """
    metrics = {
        "reachable": False,
        "cpu": 0,
        "memory": {"used": "0", "total": "0", "percent": 0},
        "disk": {"used": "0", "total": "0", "percent": 0},
        "swap": {"used": "0", "total": "0", "percent": 0},
        "load": {"1m": 0, "5m": 0, "15m": 0},
        "uptime": ""
    }
    
    try:
        # Test SSH connectivity
        test = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=3', '-o', 'BatchMode=yes', 
             f'{ssh_user}@{vm_ip}', 'echo OK'],
            capture_output=True, text=True, timeout=5
        )
        
        if 'OK' not in test.stdout:
            return metrics
        
        metrics["reachable"] = True
        
        # Get memory info
        mem = subprocess.run(
            ['ssh', f'{ssh_user}@{vm_ip}', 'free -m | grep Mem:'],
            capture_output=True, text=True, timeout=5
        )
        if mem.stdout:
            parts = mem.stdout.split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                metrics["memory"] = {
                    "used": f"{used}M",
                    "total": f"{total}M",
                    "percent": round((used / total) * 100, 1) if total > 0 else 0
                }
        
        # Get disk info
        disk = subprocess.run(
            ['ssh', f'{ssh_user}@{vm_ip}', 'df -h / | tail -1'],
            capture_output=True, text=True, timeout=5
        )
        if disk.stdout:
            parts = disk.stdout.split()
            if len(parts) >= 5:
                metrics["disk"] = {
                    "used": parts[2],
                    "total": parts[1],
                    "percent": int(parts[4].replace('%', ''))
                }
        
        # Get load average
        load = subprocess.run(
            ['ssh', f'{ssh_user}@{vm_ip}', 'cat /proc/loadavg'],
            capture_output=True, text=True, timeout=5
        )
        if load.stdout:
            parts = load.stdout.split()
            if len(parts) >= 3:
                metrics["load"] = {
                    "1m": float(parts[0]),
                    "5m": float(parts[1]),
                    "15m": float(parts[2])
                }
        
        # Get CPU usage (simple snapshot)
        cpu = subprocess.run(
            ['ssh', f'{ssh_user}@{vm_ip}', 
             "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1"],
            capture_output=True, text=True, timeout=5
        )
        if cpu.stdout.strip():
            try:
                metrics["cpu"] = float(cpu.stdout.strip())
            except ValueError:
                pass
        
        # Get swap
        swap = subprocess.run(
            ['ssh', f'{ssh_user}@{vm_ip}', 'free -m | grep Swap:'],
            capture_output=True, text=True, timeout=5
        )
        if swap.stdout:
            parts = swap.stdout.split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                metrics["swap"] = {
                    "used": f"{used}M",
                    "total": f"{total}M",
                    "percent": round((used / total) * 100, 1) if total > 0 else 0
                }
        
        # Get uptime
        uptime_result = subprocess.run(
            ['ssh', f'{ssh_user}@{vm_ip}', 'uptime -p'],
            capture_output=True, text=True, timeout=5
        )
        if uptime_result.stdout:
            metrics["uptime"] = uptime_result.stdout.strip()
        
    except (subprocess.TimeoutExpired, Exception) as e:
        metrics["error"] = str(e)
    
    return metrics


# ============================================================
# SELF-TEST
# ============================================================
if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("Output Parser Self-Test")
    print("=" * 60)
    
    # Test with sample output
    sample_physical = """
  ┌─ Physical Layer: eth0
  │  Type: ethernet
  │  ✅ Carrier: present
  │  ✅ State: up
  │  Speed: 1000Mb/s
  │  Duplex: Full
  │  ✅ Link detected: yes
  └──────────────────────────────
"""
    
    result = OutputParser.parse_physical_diagnostic(sample_physical)
    print(f"\nPhysical Layer: {result.status.value} - {result.message}")
    print(f"Details: {json.dumps(result.details, indent=2)}")
    
    sample_dns = """
  ✅ DNS resolution works (google.com)
"""
    result = OutputParser.parse_dns_diagnostic(sample_dns)
    print(f"\nDNS: {result.status.value} - {result.message}")
    
    print("\n✅ Parser module ready!")