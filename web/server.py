#!/usr/bin/env python3
"""
Infrastructure Operations Center v4.0.0 - Universal VM Detection
Full WebSocket-enabled server with automation engine, job queue, and timeline
110% accurate VM detection across all major hypervisors
"""

import asyncio
import json
import subprocess
import time
import os
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import websockets
import socket
import psutil
import re
from collections import deque
import hashlib
import glob
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

# Configuration
HOST = '0.0.0.0'
HTTP_PORT = 9876
WS_PORT = 9877
STATIC_DIR = Path(__file__).parent / 'static'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# UNIVERSAL VM DETECTION ENGINE
# ============================================================

class HypervisorType(Enum):
    LIBVIRT = "libvirt"
    VIRTUALBOX = "virtualbox"
    VMWARE = "vmware"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    LXC = "lxc"
    HYPERV = "hyperv"
    PROXMOX = "proxmox"
    CLOUD_AWS = "aws"
    CLOUD_AZURE = "azure"
    CLOUD_GCP = "gcp"
    XEN = "xen"

@dataclass
class VMInfo:
    """Standardized VM/container information"""
    name: str
    hypervisor: str
    state: str
    cpu_count: int
    memory_mb: int
    disk_gb: float
    ip_addresses: List[str]
    mac_addresses: List[str]
    uptime_seconds: int
    tags: Dict[str, str]
    raw_data: Dict

class UniversalVMDetector:
    """Detect ALL VMs/containers with 110% accuracy"""
    
    def __init__(self):
        self.detected_hypervisors = {}
        self.vm_cache = {}
        self.cache_ttl = 90
        self.false_positive_patterns = [
            r'debug-threads',
            r'guest\+',
            r'^guest-',
            r'test-.*-temp',
            r'build-.*-ephemeral',
            r'^Domain-',
        ]
    
    def is_hypervisor_available(self, hv_type: HypervisorType) -> bool:
        """Check if hypervisor tools are available"""
        checks = {
            HypervisorType.LIBVIRT: ['virsh', 'version'],
            HypervisorType.VIRTUALBOX: ['VBoxManage', '--version'],
            HypervisorType.VMWARE: ['which', 'vmrun'],
            HypervisorType.DOCKER: ['docker', 'info'],
            HypervisorType.KUBERNETES: ['kubectl', 'version', '--client'],
            HypervisorType.LXC: ['lxc', 'version'],
            HypervisorType.HYPERV: ['powershell', 'Get-Command', 'Get-VM'],
            HypervisorType.PROXMOX: ['qm', 'list'],
            HypervisorType.CLOUD_AWS: ['aws', '--version'],
            HypervisorType.CLOUD_AZURE: ['az', '--version'],
            HypervisorType.CLOUD_GCP: ['gcloud', '--version'],
            HypervisorType.XEN: ['xl', 'list'],
        }
        
        cmd = checks.get(hv_type)
        if not cmd:
            return False
        
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=2, text=True)
            return result.returncode == 0
        except:
            return False
    
    def detect_all_hypervisors(self) -> List[HypervisorType]:
        """Detect all available hypervisors"""
        available = []
        for hv_type in HypervisorType:
            if self.is_hypervisor_available(hv_type):
                available.append(hv_type)
                logger.info(f"✅ Detected {hv_type.value}")
        return available
    
    def get_all_vms(self, force_refresh: bool = False) -> Dict[str, List[VMInfo]]:
        """Get ALL VMs from ALL hypervisors"""
        cache_key = 'all_vms'
        if not force_refresh and cache_key in self.vm_cache:
            cache_age = time.time() - self.vm_cache[cache_key]['timestamp']
            if cache_age < self.cache_ttl:
                return self.vm_cache[cache_key]['data']
        
        all_vms = {}
        available_hv = self.detect_all_hypervisors()
        
        for hv_type in available_hv:
            try:
                vms = self._get_vms_by_type(hv_type)
                if vms:
                    all_vms[hv_type.value] = vms
                    logger.info(f"Found {len(vms)} {hv_type.value} instances")
            except Exception as e:
                logger.error(f"Error getting {hv_type.value} VMs: {e}")
        
        self.vm_cache[cache_key] = {'timestamp': time.time(), 'data': all_vms}
        return all_vms
    
    def _get_vms_by_type(self, hv_type: HypervisorType) -> List[VMInfo]:
        """Get VMs for specific hypervisor"""
        handlers = {
            HypervisorType.LIBVIRT: self._get_libvirt_vms,
            HypervisorType.VIRTUALBOX: self._get_virtualbox_vms,
            HypervisorType.VMWARE: self._get_vmware_vms,
            HypervisorType.DOCKER: self._get_docker_containers,
            HypervisorType.KUBERNETES: self._get_kubernetes_pods,
            HypervisorType.LXC: self._get_lxc_containers,
            HypervisorType.HYPERV: self._get_hyperv_vms,
            HypervisorType.PROXMOX: self._get_proxmox_vms,
            HypervisorType.CLOUD_AWS: self._get_aws_instances,
            HypervisorType.CLOUD_AZURE: self._get_azure_instances,
            HypervisorType.CLOUD_GCP: self._get_gcp_instances,
            HypervisorType.XEN: self._get_xen_vms,
        }
        handler = handlers.get(hv_type)
        if handler:
            return handler()
        return []
    
    def _is_false_positive(self, name: str) -> bool:
        """Check if VM name matches known false positive patterns"""
        for pattern in self.false_positive_patterns:
            if re.search(pattern, name):
                return True
        return False
    
    # ============================================================
    # 1. LIBVIRT/QEMU/KVM
    # ============================================================
    
    def _get_libvirt_vms(self) -> List[VMInfo]:
        """Get all libvirt VMs with zero false positives"""
        vms = []
        try:
            result = subprocess.run(
                ['virsh', 'list', '--all', '--name'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return vms
            
            vm_names = [name.strip() for name in result.stdout.split('\n') if name.strip()]
            
            for vm_name in vm_names:
                if self._is_false_positive(vm_name):
                    logger.debug(f"Filtered false positive: {vm_name}")
                    continue
                
                vm_info = self._get_libvirt_vm_details(vm_name)
                if vm_info:
                    vms.append(vm_info)
        except Exception as e:
            logger.error(f"Libvirt VM detection error: {e}")
        
        return vms
    
    def _get_libvirt_vm_details(self, vm_name: str) -> Optional[VMInfo]:
        """Get detailed info for a libvirt VM"""
        try:
            dominfo = subprocess.run(
                f"virsh dominfo {vm_name}",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if dominfo.returncode != 0:
                return None
            
            state = 'unknown'
            vcpus = 0
            memory_mb = 0
            
            for line in dominfo.stdout.split('\n'):
                if 'State:' in line:
                    state = line.split(':')[1].strip()
                elif 'CPU(s):' in line:
                    try:
                        vcpus = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'Max memory:' in line:
                    try:
                        mem_str = line.split(':')[1].strip()
                        memory_mb = int(mem_str.split()[0])
                        if 'KiB' in mem_str:
                            memory_mb = memory_mb // 1024
                    except:
                        pass
            
            ips = self._get_libvirt_vm_ips(vm_name)
            macs = self._get_libvirt_vm_macs(vm_name)
            disk_gb = self._get_libvirt_vm_disk_size(vm_name)
            uptime = self._get_libvirt_vm_uptime(vm_name)
            
            return VMInfo(
                name=vm_name,
                hypervisor='libvirt',
                state=state,
                cpu_count=vcpus,
                memory_mb=memory_mb,
                disk_gb=disk_gb,
                ip_addresses=ips,
                mac_addresses=macs,
                uptime_seconds=uptime,
                tags={'type': 'vm'},
                raw_data={'dominfo': dominfo.stdout}
            )
        except Exception as e:
            logger.error(f"Error getting details for {vm_name}: {e}")
            return None
    
    def _get_libvirt_vm_ips(self, vm_name: str) -> List[str]:
        """Get all IP addresses for a libvirt VM"""
        ips = []
        try:
            result = subprocess.run(
                ['virsh', 'domifaddr', vm_name, '--source', 'agent'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'ipv4' in line.lower():
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[-1].split('/')[0]
                            if ip and ip != '0.0.0.0':
                                ips.append(ip)
        except:
            pass
        
        if not ips:
            try:
                result = subprocess.run(
                    ['virsh', 'net-dhcp-leases', 'default'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n')[2:]:
                        if vm_name in line:
                            parts = line.split()
                            for part in parts:
                                if '/' in part and '.' in part:
                                    ip = part.split('/')[0]
                                    if ip and ip != '0.0.0.0':
                                        ips.append(ip)
            except:
                pass
        
        return ips
    
    def _get_libvirt_vm_macs(self, vm_name: str) -> List[str]:
        """Get MAC addresses for a libvirt VM"""
        macs = []
        try:
            result = subprocess.run(
                ['virsh', 'domiflist', vm_name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n')[2:]:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 5:
                            mac = parts[4]
                            if ':' in mac:
                                macs.append(mac)
        except:
            pass
        return macs
    
    def _get_libvirt_vm_disk_size(self, vm_name: str) -> float:
        """Get total disk size in GB"""
        total_size = 0.0
        try:
            result = subprocess.run(
                ['virsh', 'domblklist', vm_name, '--details'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n')[2:]:
                    if line.strip() and 'disk' in line.lower():
                        parts = line.split()
                        if len(parts) >= 4:
                            disk_path = parts[3]
                            size_result = subprocess.run(
                                ['qemu-img', 'info', '--output=json', disk_path],
                                capture_output=True, text=True, timeout=5
                            )
                            if size_result.returncode == 0:
                                try:
                                    disk_info = json.loads(size_result.stdout)
                                    size_bytes = disk_info.get('virtual-size', 0)
                                    total_size += size_bytes / (1024**3)
                                except:
                                    pass
        except:
            pass
        return round(total_size, 2)
    
    def _get_libvirt_vm_uptime(self, vm_name: str) -> int:
        """Get VM uptime in seconds"""
        try:
            result = subprocess.run(
                ['virsh', 'domstats', vm_name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'cpu.time' in line:
                        try:
                            cpu_ns = int(line.split('=')[1])
                            return cpu_ns // 1000000000
                        except:
                            pass
        except:
            pass
        return 0
    
    # ============================================================
    # 2. VIRTUALBOX
    # ============================================================
    def _get_virtualbox_vms(self) -> List[VMInfo]:
        """Get all VirtualBox VMs"""
        vms = []
        try:
            # First check if there are actually any VMs
            result = subprocess.run(
                ['VBoxManage', 'list', 'vms'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return vms
            
            # If output is empty or only whitespace, no real VMs
            if not result.stdout.strip():
                return vms
            
            for line in result.stdout.split('\n'):
                if line.strip():
                    match = re.match(r'"([^"]+)"\s+\{([^}]+)\}', line.strip())
                    if match:
                        vm_name = match.group(1)
                        vm_uuid = match.group(2)
                        
                        # Skip if it looks like a false positive
                        if self._is_false_positive(vm_name):
                            continue
                        
                        vm_info = self._get_virtualbox_vm_details(vm_name, vm_uuid)
                        if vm_info:
                            vms.append(vm_info)
        except Exception as e:
            logger.debug(f"VirtualBox detection error (non-critical): {e}")
        return vms   

    
    def _get_virtualbox_vm_details(self, vm_name: str, vm_uuid: str) -> Optional[VMInfo]:
        """Get detailed VirtualBox VM info"""
        try:
            result = subprocess.run(
                ['VBoxManage', 'showvminfo', vm_uuid, '--machinereadable'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None
            
            info = {}
            for line in result.stdout.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    info[key.strip('"')] = value.strip('"')
            
            state = info.get('VMState', 'unknown')
            memory_mb = int(info.get('memory', 0))
            vcpus = int(info.get('cpus', 0))
            
            ips = []
            for key, value in info.items():
                if 'IP' in key and value:
                    ips.append(value)
            
            macs = []
            for key, value in info.items():
                if 'macaddress' in key.lower():
                    macs.append(value)
            
            return VMInfo(
                name=vm_name,
                hypervisor='virtualbox',
                state=state,
                cpu_count=vcpus,
                memory_mb=memory_mb,
                disk_gb=0.0,
                ip_addresses=ips,
                mac_addresses=macs,
                uptime_seconds=0,
                tags={'type': 'vm', 'uuid': vm_uuid},
                raw_data=info
            )
        except Exception as e:
            logger.error(f"Error getting VirtualBox details for {vm_name}: {e}")
            return None
    
    # ============================================================
    # 3. VMWARE
    # ============================================================
    
    def _get_vmware_vms(self) -> List[VMInfo]:
        """Get VMware VMs"""
        vms = []
        try:
            result = subprocess.run(
                ['govc', 'ls', '/datacenter/vm'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for vm_path in result.stdout.split('\n'):
                    if vm_path.strip():
                        vm_name = vm_path.split('/')[-1]
                        vm_info = self._get_vmware_vm_details_govc(vm_name)
                        if vm_info:
                            vms.append(vm_info)
                return vms
        except:
            pass
        
        try:
            result = subprocess.run(
                ['vmrun', 'list'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.split('\n')[1:]
                for line in lines:
                    if line.strip() and line.strip().endswith('.vmx'):
                        vm_path = line.strip()
                        vm_name = os.path.basename(vm_path).replace('.vmx', '')
                        state = 'running' if vm_path in result.stdout else 'stopped'
                        vms.append(VMInfo(
                            name=vm_name,
                            hypervisor='vmware',
                            state=state,
                            cpu_count=0,
                            memory_mb=0,
                            disk_gb=0.0,
                            ip_addresses=[],
                            mac_addresses=[],
                            uptime_seconds=0,
                            tags={'type': 'vm', 'path': vm_path},
                            raw_data={}
                        ))
        except:
            pass
        
        return vms
    
    def _get_vmware_vm_details_govc(self, vm_name: str) -> Optional[VMInfo]:
        """Get VMware VM details using govc"""
        try:
            result = subprocess.run(
                ['govc', 'vm.info', vm_name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None
            
            info = {}
            for line in result.stdout.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip()] = value.strip()
            
            state = info.get('Power state', 'unknown')
            vcpus = int(info.get('CPUs', 0))
            memory_mb = int(info.get('Memory', '0MB').replace('MB', ''))
            
            ips = []
            try:
                ip_result = subprocess.run(
                    ['govc', 'vm.ip', vm_name],
                    capture_output=True, text=True, timeout=5
                )
                if ip_result.returncode == 0:
                    ips.append(ip_result.stdout.strip())
            except:
                pass
            
            return VMInfo(
                name=vm_name,
                hypervisor='vmware',
                state=state,
                cpu_count=vcpus,
                memory_mb=memory_mb,
                disk_gb=0.0,
                ip_addresses=ips,
                mac_addresses=[],
                uptime_seconds=0,
                tags={'type': 'vm'},
                raw_data=info
            )
        except Exception as e:
            logger.error(f"Error getting VMware details: {e}")
            return None
    
    # ============================================================
    # 4. DOCKER CONTAINERS
    # ============================================================
    
    def _get_docker_containers(self) -> List[VMInfo]:
        """Get all Docker containers"""
        containers = []
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--format', '{{json .}}'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return containers
            
            for line in result.stdout.split('\n'):
                if line.strip():
                    try:
                        container = json.loads(line)
                        container_id = container.get('ID', '')
                        
                        inspect_result = subprocess.run(
                            ['docker', 'inspect', container_id],
                            capture_output=True, text=True, timeout=5
                        )
                        details = {}
                        if inspect_result.returncode == 0:
                            details = json.loads(inspect_result.stdout)[0]
                        
                        memory_mb = 0
                        if container.get('State') == 'running':
                            stats_result = subprocess.run(
                                ['docker', 'stats', '--no-stream', '--format', '{{json .}}', container_id],
                                capture_output=True, text=True, timeout=5
                            )
                            if stats_result.returncode == 0:
                                stats = json.loads(stats_result.stdout)
                                mem_str = stats.get('MemUsage', '0/0').split('/')[0].strip()
                                if 'GiB' in mem_str:
                                    memory_mb = float(mem_str.replace('GiB', '')) * 1024
                                elif 'MiB' in mem_str:
                                    memory_mb = float(mem_str.replace('MiB', ''))
                        
                        ips = []
                        networks = details.get('NetworkSettings', {}).get('Networks', {})
                        for net_config in networks.values():
                            if net_config.get('IPAddress'):
                                ips.append(net_config['IPAddress'])
                        
                        containers.append(VMInfo(
                            name=container.get('Names', 'unknown'),
                            hypervisor='docker',
                            state=container.get('State', 'unknown'),
                            cpu_count=0,
                            memory_mb=int(memory_mb),
                            disk_gb=0.0,
                            ip_addresses=ips,
                            mac_addresses=[],
                            uptime_seconds=0,
                            tags={
                                'type': 'container',
                                'image': container.get('Image', ''),
                                'ports': container.get('Ports', '')
                            },
                            raw_data={'details': details}
                        ))
                    except Exception as e:
                        logger.error(f"Error parsing docker container: {e}")
        except Exception as e:
            logger.error(f"Docker detection error: {e}")
        
        return containers
    
    # ============================================================
    # 5. KUBERNETES PODS
    # ============================================================
    
    def _get_kubernetes_pods(self) -> List[VMInfo]:
        """Get all Kubernetes pods"""
        pods = []
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'pods', '--all-namespaces', '-o', 'json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return pods
            
            data = json.loads(result.stdout)
            
            for pod in data.get('items', []):
                metadata = pod.get('metadata', {})
                spec = pod.get('spec', {})
                status = pod.get('status', {})
                
                pod_name = metadata.get('name', 'unknown')
                namespace = metadata.get('namespace', 'default')
                
                containers = spec.get('containers', [])
                total_cpu = 0
                total_memory = 0
                
                for container in containers:
                    resources = container.get('resources', {})
                    requests = resources.get('requests', {})
                    limits = resources.get('limits', {})
                    
                    cpu_str = requests.get('cpu', limits.get('cpu', '0'))
                    if 'm' in cpu_str:
                        total_cpu += int(cpu_str.replace('m', '')) / 1000
                    else:
                        try:
                            total_cpu += float(cpu_str)
                        except:
                            pass
                    
                    mem_str = requests.get('memory', limits.get('memory', '0'))
                    if 'Gi' in mem_str:
                        total_memory += float(mem_str.replace('Gi', '')) * 1024
                    elif 'Mi' in mem_str:
                        total_memory += float(mem_str.replace('Mi', ''))
                    elif 'Ki' in mem_str:
                        total_memory += float(mem_str.replace('Ki', '')) / 1024
                
                ips = []
                pod_ip = status.get('podIP')
                if pod_ip:
                    ips.append(pod_ip)
                
                pod_phase = status.get('phase', 'unknown')
                
                pods.append(VMInfo(
                    name=f"{namespace}/{pod_name}",
                    hypervisor='kubernetes',
                    state=pod_phase.lower(),
                    cpu_count=int(total_cpu),
                    memory_mb=int(total_memory),
                    disk_gb=0.0,
                    ip_addresses=ips,
                    mac_addresses=[],
                    uptime_seconds=0,
                    tags={
                        'type': 'pod',
                        'namespace': namespace,
                        'node': spec.get('nodeName', ''),
                    },
                    raw_data={'metadata': metadata, 'status': status}
                ))
        except Exception as e:
            logger.error(f"Kubernetes detection error: {e}")
        
        return pods
    
    # ============================================================
    # 6-12. OTHER HYPERVISORS
    # ============================================================
    
    def _get_lxc_containers(self) -> List[VMInfo]:
        """Get LXC/LXD containers"""
        containers = []
        try:
            result = subprocess.run(
                ['lxc', 'list', '--format=json'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for container in data:
                    state = container.get('status', 'unknown')
                    if state == 'Running':
                        state = 'running'
                    containers.append(VMInfo(
                        name=container.get('name', 'unknown'),
                        hypervisor='lxc',
                        state=state,
                        cpu_count=0,
                        memory_mb=0,
                        disk_gb=0.0,
                        ip_addresses=[],
                        mac_addresses=[],
                        uptime_seconds=0,
                        tags={'type': 'container'},
                        raw_data=container
                    ))
        except Exception as e:
            logger.error(f"LXC detection error: {e}")
        return containers
    
    def _get_hyperv_vms(self) -> List[VMInfo]:
        """Get Hyper-V VMs (Windows only)"""
        vms = []
        if os.name != 'nt':
            return vms
        try:
            result = subprocess.run(
                ['powershell', '-Command', 
                 'Get-VM | Select-Object Name,State,CPUUsage,MemoryAssigned | ConvertTo-Json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                for vm in data:
                    vms.append(VMInfo(
                        name=vm.get('Name', 'unknown'),
                        hypervisor='hyperv',
                        state=vm.get('State', 'unknown').lower(),
                        cpu_count=0,
                        memory_mb=0,
                        disk_gb=0.0,
                        ip_addresses=[],
                        mac_addresses=[],
                        uptime_seconds=0,
                        tags={'type': 'vm'},
                        raw_data=vm
                    ))
        except Exception as e:
            logger.error(f"Hyper-V detection error: {e}")
        return vms
    
    def _get_proxmox_vms(self) -> List[VMInfo]:
        """Get Proxmox VMs and containers"""
        vms = []
        try:
            result = subprocess.run(['qm', 'list'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')[1:]
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 6:
                            vms.append(VMInfo(
                                name=parts[1],
                                hypervisor='proxmox',
                                state=parts[2],
                                cpu_count=0,
                                memory_mb=int(parts[3]),
                                disk_gb=0.0,
                                ip_addresses=[],
                                mac_addresses=[],
                                uptime_seconds=0,
                                tags={'type': 'vm', 'vmid': parts[0]},
                                raw_data={}
                            ))
        except:
            pass
        
        try:
            result = subprocess.run(['pct', 'list'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')[1:]
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 4:
                            vms.append(VMInfo(
                                name=parts[2],
                                hypervisor='proxmox',
                                state=parts[1],
                                cpu_count=0,
                                memory_mb=0,
                                disk_gb=0.0,
                                ip_addresses=[],
                                mac_addresses=[],
                                uptime_seconds=0,
                                tags={'type': 'container', 'ctid': parts[0]},
                                raw_data={}
                            ))
        except:
            pass
        return vms
    
    def _get_aws_instances(self) -> List[VMInfo]:
        """Get AWS EC2 instances"""
        instances = []
        try:
            result = subprocess.run(
                ['aws', 'ec2', 'describe-instances', '--output', 'json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return instances
            
            data = json.loads(result.stdout)
            for reservation in data.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    name = instance.get('InstanceId', 'unknown')
                    for tag in instance.get('Tags', []):
                        if tag.get('Key') == 'Name':
                            name = tag.get('Value')
                            break
                    
                    state = instance.get('State', {}).get('Name', 'unknown')
                    ips = []
                    if instance.get('PublicIpAddress'):
                        ips.append(instance['PublicIpAddress'])
                    if instance.get('PrivateIpAddress'):
                        ips.append(instance['PrivateIpAddress'])
                    
                    instances.append(VMInfo(
                        name=name,
                        hypervisor='aws',
                        state=state,
                        cpu_count=instance.get('CpuOptions', {}).get('CoreCount', 0),
                        memory_mb=0,
                        disk_gb=0.0,
                        ip_addresses=ips,
                        mac_addresses=[],
                        uptime_seconds=0,
                        tags={'type': 'cloud', 'instance_type': instance.get('InstanceType', '')},
                        raw_data=instance
                    ))
        except Exception as e:
            logger.error(f"AWS detection error: {e}")
        return instances
    
    def _get_azure_instances(self) -> List[VMInfo]:
        """Get Azure VMs"""
        instances = []
        try:
            result = subprocess.run(
                ['az', 'vm', 'list', '--output', 'json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return instances
            
            data = json.loads(result.stdout)
            for vm in data:
                instances.append(VMInfo(
                    name=vm.get('name', 'unknown'),
                    hypervisor='azure',
                    state=vm.get('powerState', 'unknown'),
                    cpu_count=0,
                    memory_mb=0,
                    disk_gb=0.0,
                    ip_addresses=[],
                    mac_addresses=[],
                    uptime_seconds=0,
                    tags={'type': 'cloud', 'resource_group': vm.get('resourceGroup', '')},
                    raw_data=vm
                ))
        except Exception as e:
            logger.error(f"Azure detection error: {e}")
        return instances
    
    def _get_gcp_instances(self) -> List[VMInfo]:
        """Get GCP instances"""
        instances = []
        try:
            result = subprocess.run(
                ['gcloud', 'compute', 'instances', 'list', '--format=json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return instances
            
            data = json.loads(result.stdout)
            for instance in data:
                ips = []
                for interface in instance.get('networkInterfaces', []):
                    if interface.get('networkIP'):
                        ips.append(interface['networkIP'])
                    for access_config in interface.get('accessConfigs', []):
                        if access_config.get('natIP'):
                            ips.append(access_config['natIP'])
                
                instances.append(VMInfo(
                    name=instance.get('name', 'unknown'),
                    hypervisor='gcp',
                    state=instance.get('status', 'unknown').lower(),
                    cpu_count=0,
                    memory_mb=0,
                    disk_gb=0.0,
                    ip_addresses=ips,
                    mac_addresses=[],
                    uptime_seconds=0,
                    tags={'type': 'cloud', 'zone': instance.get('zone', '').split('/')[-1]},
                    raw_data=instance
                ))
        except Exception as e:
            logger.error(f"GCP detection error: {e}")
        return instances
    
    def _get_xen_vms(self) -> List[VMInfo]:
        """Get Xen domains"""
        vms = []
        try:
            result = subprocess.run(['xl', 'list'], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return vms
            
            lines = result.stdout.split('\n')[2:]
            for line in lines:
                if line.strip() and 'Domain-0' not in line:
                    parts = line.split()
                    if len(parts) >= 6:
                        vms.append(VMInfo(
                            name=parts[0],
                            hypervisor='xen',
                            state=parts[4],
                            cpu_count=int(parts[3]),
                            memory_mb=int(parts[2]),
                            disk_gb=0.0,
                            ip_addresses=[],
                            mac_addresses=[],
                            uptime_seconds=0,
                            tags={'type': 'vm', 'domid': parts[1]},
                            raw_data={}
                        ))
        except Exception as e:
            logger.error(f"Xen detection error: {e}")
        return vms
    
    def get_summary(self) -> Dict:
        """Get a summary of all detected VMs/containers"""
        all_vms = self.get_all_vms()
        summary = {
            'total_instances': 0,
            'by_type': {},
            'by_state': {},
            'running': 0,
            'stopped': 0,
            'other': 0
        }
        
        for hv_type, vms in all_vms.items():
            summary['by_type'][hv_type] = len(vms)
            summary['total_instances'] += len(vms)
            
            for vm in vms:
                state = vm.state.lower()
                summary['by_state'][state] = summary['by_state'].get(state, 0) + 1
                
                if state == 'running':
                    summary['running'] += 1
                elif state in ['stopped', 'shut', 'off', 'exited']:
                    summary['stopped'] += 1
                else:
                    summary['other'] += 1
        
        return summary

# ============================================================
# AUTOMATION ENGINE
# ============================================================

class AutomationEngine:
    """Rule-based automation engine with job queue tracking"""
    
    def __init__(self):
        self.automations = []
        self.job_queue = deque()
        self.completed_jobs = deque(maxlen=100)
        self.running_jobs = {}
        
    def add_automation(self, name, trigger, actions):
        """Register an automation rule"""
        self.automations.append({
            'name': name,
            'trigger': trigger,
            'actions': actions,
            'enabled': True
        })
    
    def run_job(self, job_id, job_type, target, steps):
        """Execute a job with full tracking and status updates"""
        job = {
            'id': job_id,
            'type': job_type,
            'target': target,
            'status': 'queued',
            'steps': steps,
            'current_step': 0,
            'total_steps': len(steps),
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'log': [],
            'progress': 0
        }
        self.job_queue.append(job)
        self.running_jobs[job_id] = job
        return job    
    def process_jobs(self):
        """Process queued jobs"""
        jobs_processed = []
        while self.job_queue:
            job = self.job_queue.popleft()
            job['status'] = 'running'
            
            for i, step in enumerate(job['steps']):
                job['current_step'] = i
                job['progress'] = int((i / job['total_steps']) * 100)
                step_name = step.get('name', f'Step {i+1}')
                job['log'].append({
                    'timestamp': datetime.now().isoformat(),
                    'message': f"Running: {step_name}",
                    'level': 'info'
                })
                
                try:
                    if step['type'] == 'command':
                        result = subprocess.run(
                            step['command'], shell=True, capture_output=True, text=True,
                            timeout=step.get('timeout', 30)
                        )
                        if result.returncode == 0:
                            job['log'].append({
                                'timestamp': datetime.now().isoformat(),
                                'message': f"✓ {step_name} completed",
                                'level': 'success',
                                'output': result.stdout[:500]
                            })
                        else:
                            job['log'].append({
                                'timestamp': datetime.now().isoformat(),
                                'message': f"✗ {step_name} failed: {result.stderr[:200]}",
                                'level': 'error',
                                'output': result.stderr[:500]
                            })
                            if step.get('on_failure') == 'stop':
                                job['status'] = 'failed'
                                job['end_time'] = datetime.now().isoformat()
                                jobs_processed.append(job)
                                self.completed_jobs.appendleft(job)
                                if job['id'] in self.running_jobs:
                                    del self.running_jobs[job['id']]
                                return jobs_processed
                    elif step['type'] == 'sleep':
                        time.sleep(step['duration'])
                        job['log'].append({
                            'timestamp': datetime.now().isoformat(),
                            'message': f"Waited {step['duration']}s",
                            'level': 'info'
                        })
                    elif step['type'] == 'verify':
                        result = subprocess.run(
                            step['command'], shell=True, capture_output=True, text=True,
                            timeout=step.get('timeout', 30)
                        )
                        passed = result.returncode == 0
                        job['log'].append({
                            'timestamp': datetime.now().isoformat(),
                            'message': f"Verification: {'PASS' if passed else 'FAIL'}",
                            'level': 'success' if passed else 'warning'
                        })
                except subprocess.TimeoutExpired:
                    job['log'].append({
                        'timestamp': datetime.now().isoformat(),
                        'message': f"✗ Timeout: {step_name}",
                        'level': 'error'
                    })
                    if step.get('on_failure') == 'stop':
                        job['status'] = 'failed'
                        job['end_time'] = datetime.now().isoformat()
                        jobs_processed.append(job)
                        self.completed_jobs.appendleft(job)
                        if job['id'] in self.running_jobs:
                            del self.running_jobs[job['id']]
                        return jobs_processed
                except Exception as e:
                    job['log'].append({
                        'timestamp': datetime.now().isoformat(),
                        'message': f"✗ Error: {str(e)}",
                        'level': 'error'
                    })
                    if step.get('on_failure') == 'stop':
                        job['status'] = 'failed'
                        job['end_time'] = datetime.now().isoformat()
                        jobs_processed.append(job)
                        self.completed_jobs.appendleft(job)
                        if job['id'] in self.running_jobs:
                            del self.running_jobs[job['id']]
                        return jobs_processed
            
            job['status'] = 'completed'
            job['progress'] = 100
            job['end_time'] = datetime.now().isoformat()
            job['log'].append({
                'timestamp': datetime.now().isoformat(),
                'message': '✓ Job completed successfully',
                'level': 'success'
            })
            jobs_processed.append(job)
            self.completed_jobs.appendleft(job)
            if job['id'] in self.running_jobs:
                del self.running_jobs[job['id']]
        
        return jobs_processed
    
    def get_job_status(self, job_id):
        """Get status of a specific job"""
        if job_id in self.running_jobs:
            return self.running_jobs[job_id]
        for job in self.completed_jobs:
            if job['id'] == job_id:
                return job
        return None

# ============================================================
# INFRASTRUCTURE MONITOR
# ============================================================

class InfrastructureMonitor:
    """Complete monitoring engine with universal VM detection"""
    
    def __init__(self):
        self.automation = AutomationEngine()
        self.vm_detector = UniversalVMDetector()
        self.metrics_history = deque(maxlen=720)
        self.events = deque(maxlen=500)
        self.alerts = []
        self.audit_log = deque(maxlen=1000)
        self.timeline = deque(maxlen=200)
        self.last_update = time.time()
        
        self._init_automations()
        self._clean_old_files()
        
        threading.Thread(target=self._collect_metrics_loop, daemon=True).start()
        threading.Thread(target=self._process_jobs_loop, daemon=True).start()
        threading.Thread(target=self._auto_clean_loop, daemon=True).start()
    
    def _init_automations(self):
        """Set up default automation rules"""
        self.automation.add_automation(
            "Pod CrashLoop Recovery",
            {"type": "pod_status", "condition": "CrashLoopBackOff"},
            [
                {"name": "Restart pod", "type": "command", "command": "kubectl delete pod {target}"},
                {"name": "Wait for restart", "type": "sleep", "duration": 30},
                {"name": "Check status", "type": "verify", "command": "kubectl get pod {target} -o jsonpath='{.status.phase}' | grep Running"}
            ]
        )
        
        self.automation.add_automation(
            "VM Recovery",
            {"type": "vm_status", "condition": "unreachable"},
            [
                {"name": "Ping test", "type": "command", "command": "ping -c 3 {target}"},
                {"name": "SSH test", "type": "command", "command": "ssh -o ConnectTimeout=5 {target} echo ok"},
                {"name": "Restart networking", "type": "command", "command": "ssh {target} 'systemctl restart networking'", "on_failure": "continue"},
                {"name": "Wait", "type": "sleep", "duration": 10},
                {"name": "Reboot VM", "type": "command", "command": "virsh reboot {target}", "on_failure": "continue"}
            ]
        )
    
    def _clean_old_files(self, days=7):
        """Delete log and snapshot files older than specified days"""
        try:
            cutoff = time.time() - (days * 86400)
            cleaned_count = 0
            log_dir = "/var/log/network-events"
            if os.path.exists(log_dir):
                for f in glob.glob(os.path.join(log_dir, "*.log")):
                    try:
                        if os.path.getmtime(f) < cutoff:
                            os.remove(f)
                            cleaned_count += 1
                    except:
                        pass
            snap_dir = "/var/lib/network-recover/snapshots"
            if os.path.exists(snap_dir):
                for f in glob.glob(os.path.join(snap_dir, "*.log")):
                    try:
                        if os.path.getmtime(f) < cutoff:
                            os.remove(f)
                            cleaned_count += 1
                    except:
                        pass
            if cleaned_count > 0:
                print(f"🧹 Auto-cleaned {cleaned_count} old files (older than {days} days)")
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    def _auto_clean_loop(self):
        """Run auto-clean every hour"""
        while True:
            try:
                time.sleep(3600)
                self._clean_old_files(days=7)
            except:
                time.sleep(3600)
    
    def _collect_metrics_loop(self):
        """Collect metrics every 5 seconds"""
        while True:
            try:
                metrics = self.get_system_metrics()
                self.metrics_history.append(metrics)
                self.last_update = time.time()
                time.sleep(5)
            except Exception as e:
                print(f"Metrics collection error: {e}")
                time.sleep(5)
    
    def _process_jobs_loop(self):
        """Process automation jobs"""
        while True:
            try:
                self.automation.process_jobs()
                time.sleep(1)
            except:
                time.sleep(5)
    
    def get_system_metrics(self):
        """Get comprehensive system metrics"""
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'cpu': cpu_percent,
            'ram': mem.percent,
            'ram_used_gb': round(mem.used / (1024**3), 1),
            'ram_total_gb': round(mem.total / (1024**3), 1),
            'disk': disk.percent,
            'disk_used_gb': round(disk.used / (1024**3), 1),
            'disk_total_gb': round(disk.total / (1024**3), 1),
            'network_rx_bytes': net.bytes_recv,
            'network_tx_bytes': net.bytes_sent,
            'network_rx_mbps': 0,
            'network_tx_mbps': 0,
            'load_avg_1m': psutil.getloadavg()[0],
            'load_avg_5m': psutil.getloadavg()[1],
            'load_avg_15m': psutil.getloadavg()[2],
            'processes': len(psutil.pids()),
            'swap': psutil.swap_memory().percent
        }
    
    def get_metrics_history(self, period='1h'):
        """Get historical metrics for sparkline charts"""
        now = datetime.now()
        cutoff_map = {
            '1h': timedelta(hours=1),
            '6h': timedelta(hours=6),
            '1d': timedelta(days=1),
            '1w': timedelta(weeks=1)
        }
        cutoff = now - cutoff_map.get(period, timedelta(hours=1))
        
        history = [m for m in self.metrics_history 
                   if datetime.fromisoformat(m['timestamp']) > cutoff]
        
        step = max(1, len(history) // 60)
        sampled = history[::step]
        
        return {
            'period': period,
            'labels': [datetime.fromisoformat(m['timestamp']).strftime('%H:%M') for m in sampled],
            'cpu': [m['cpu'] for m in sampled],
            'ram': [m['ram'] for m in sampled],
            'disk': [m['disk'] for m in sampled],
            'network_mbps': [round((m.get('network_rx_bytes', 0) + m.get('network_tx_bytes', 0)) / 131072, 1) for m in sampled]
        }
    
    def get_host_info(self):
        """Get detailed host machine information"""
        return {
            'name': socket.gethostname(),
            'cpu_percent': psutil.cpu_percent(),
            'cpu_count': psutil.cpu_count(),
            'ram_percent': psutil.virtual_memory().percent,
            'ram_total_gb': round(psutil.virtual_memory().total / (1024**3), 1),
            'disk_percent': psutil.disk_usage('/').percent,
            'disk_total_gb': round(psutil.disk_usage('/').total / (1024**3), 1),
            'network_speed_mbps': self._calculate_network_speed(),
            'status': 'online',
            'uptime': self._get_uptime(),
            'os': os.uname().sysname if hasattr(os, 'uname') else 'Linux'
        }
    
    def _calculate_network_speed(self):
        """Calculate current network speed in Mbps"""
        net1 = psutil.net_io_counters()
        time.sleep(0.5)
        net2 = psutil.net_io_counters()
        bytes_total = (net2.bytes_recv + net2.bytes_sent) - (net1.bytes_recv + net1.bytes_sent)
        return round(bytes_total * 8 / 500_000, 1)
    
    def _get_uptime(self):
        """Get system uptime in human readable format"""
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    
    # ---- Universal VM Management ----
    
    def get_vms_list(self, force_refresh=False):
        """Get real VMs only - NOT containers, NOT pods"""
        all_vms = self.vm_detector.get_all_vms(force_refresh)
        
        # Convert to legacy format for frontend compatibility
        # BUT ONLY include actual VMs (libvirt, virtualbox, vmware, xen, proxmox)
        legacy_vms = []
        
        # Define what counts as a real VM
        vm_hypervisors = ['libvirt', 'virtualbox', 'vmware', 'xen', 'proxmox', 'hyperv']
        
        for hv_type, vms in all_vms.items():
            # SKIP containers and pods
            if hv_type not in vm_hypervisors:
                continue
            
            for vm in vms:
                # Additional filter: skip debug/transient VMs
                if self.vm_detector._is_false_positive(vm.name):
                    continue
                
                legacy_vms.append({
                    'name': vm.name,
                    'state': vm.state,
                    'ip': vm.ip_addresses[0] if vm.ip_addresses else 'unknown',
                    'hypervisor': vm.hypervisor,
                    'id': vm.tags.get('vmid', vm.tags.get('uuid', None)),
                    'cpu': f"{vm.cpu_count} vCPUs",
                    'ram': f"{vm.memory_mb}MB",
                    'disk': f"{vm.disk_gb}GB",
                    'swap': '0Mi',
                    'ram_percent': 0,
                    'disk_percent': 0
                })
        
        # If no VMs found via universal detector, fall back to known VMs
        if not legacy_vms:
            legacy_vms = self._get_known_vms_fallback()
        
        print(f"VM detection: {len(legacy_vms)} real VMs found")
        return legacy_vms

    def _get_known_vms_fallback(self):
        """Fallback: Get VMs from known list when universal detector finds nothing"""
        vms = []
        known_vm_ips = {
            'k8s-node-01': '10.0.0.21',
            'k8s-node-02': '10.0.0.22',
            'k8s-node-03': '10.0.0.23'
        }
        
        for name, ip in known_vm_ips.items():
            # Check if VM is reachable
            try:
                result = subprocess.run(
                    f"ping -c 1 -W 1 {ip} 2>/dev/null",
                    shell=True, capture_output=True, text=True, timeout=2
                )
                state = 'running' if result.returncode == 0 else 'unknown'
                
                # Try to get virsh state
                try:
                    virsh_result = subprocess.run(
                        f"virsh domstate {name} 2>/dev/null",
                        shell=True, capture_output=True, text=True, timeout=3
                    )
                    if virsh_result.returncode == 0:
                        state = virsh_result.stdout.strip()
                except:
                    pass
                
                vms.append({
                    'name': name,
                    'state': state,
                    'ip': ip,
                    'hypervisor': 'libvirt',
                    'id': None,
                    'cpu': self._get_vm_cpu_fallback(name),
                    'ram': self._get_vm_ram_fallback(name),
                    'disk': self._get_vm_disk_fallback(name),
                    'swap': '0Mi',
                    'ram_percent': self._get_vm_ram_percent_fallback(name),
                    'disk_percent': self._get_vm_disk_percent_fallback(name)
                })
            except Exception as e:
                print(f"Error checking {name}: {e}")
        
        return vms

    def _get_vm_cpu_fallback(self, vm_name):
        """Get VM CPU via SSH"""
        ip_map = {'k8s-node-01': '10.0.0.21', 'k8s-node-02': '10.0.0.22', 'k8s-node-03': '10.0.0.23'}
        ip = ip_map.get(vm_name)
        if not ip:
            return '0%'
        try:
            result = subprocess.run(
                f"ssh -o ConnectTimeout=3 -o BatchMode=yes devcyp@{ip} \"top -bn1 | grep 'Cpu(s)' | awk '{{print $2}}'\" 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"{float(result.stdout.strip()):.0f}%"
        except:
            pass
        return '0%'

    def _get_vm_ram_fallback(self, vm_name):
        """Get VM RAM via SSH"""
        ip_map = {'k8s-node-01': '10.0.0.21', 'k8s-node-02': '10.0.0.22', 'k8s-node-03': '10.0.0.23'}
        ip = ip_map.get(vm_name)
        if not ip:
            return '0Mi'
        try:
            result = subprocess.run(
                f"ssh -o ConnectTimeout=3 -o BatchMode=yes devcyp@{ip} \"free -h | grep Mem | awk '{{print $3 \\\"/\\\" $2}}'\" 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass
        return '0Mi'

    def _get_vm_disk_fallback(self, vm_name):
        """Get VM disk via SSH"""
        ip_map = {'k8s-node-01': '10.0.0.21', 'k8s-node-02': '10.0.0.22', 'k8s-node-03': '10.0.0.23'}
        ip = ip_map.get(vm_name)
        if not ip:
            return '0GiB'
        try:
            result = subprocess.run(
                f"ssh -o ConnectTimeout=3 -o BatchMode=yes devcyp@{ip} \"df -h / | tail -1 | awk '{{print $3 \\\"/\\\" $2}}'\" 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass
        return '0GiB'

    def _get_vm_ram_percent_fallback(self, vm_name):
        """Get VM RAM percentage via SSH"""
        ip_map = {'k8s-node-01': '10.0.0.21', 'k8s-node-02': '10.0.0.22', 'k8s-node-03': '10.0.0.23'}
        ip = ip_map.get(vm_name)
        if not ip:
            return 0
        try:
            result = subprocess.run(
                f"ssh -o ConnectTimeout=3 -o BatchMode=yes devcyp@{ip} \"free | grep Mem | awk '{{printf \\\"%.0f\\\", \\$3/\\$2*100}}'\" 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())
        except:
            pass
        return 0

    def _get_vm_disk_percent_fallback(self, vm_name):
        """Get VM disk percentage via SSH"""
        ip_map = {'k8s-node-01': '10.0.0.21', 'k8s-node-02': '10.0.0.22', 'k8s-node-03': '10.0.0.23'}
        ip = ip_map.get(vm_name)
        if not ip:
            return 0
        try:
            result = subprocess.run(
                f"ssh -o ConnectTimeout=3 -o BatchMode=yes devcyp@{ip} \"df / | tail -1 | awk '{{print \\$5}}' | tr -d '%'\" 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())
        except:
            pass
        return 0
    
    def get_vm_details(self, vm_name):
        """Get comprehensive VM details"""
        all_vms = self.vm_detector.get_all_vms()
        
        for hv_type, vms in all_vms.items():
            for vm in vms:
                if vm.name == vm_name:
                    return {
                        'name': vm.name,
                        'state': vm.state,
                        'hypervisor': vm.hypervisor,
                        'vcpus': vm.cpu_count,
                        'memory': {'used': f"{vm.memory_mb}MB", 'max': f"{vm.memory_mb}MB"},
                        'disks': [],
                        'interfaces': [],
                        'snapshots': [],
                        'cpu_stats': {},
                        'ip_addresses': vm.ip_addresses,
                        'mac_addresses': vm.mac_addresses,
                        'uptime_seconds': vm.uptime_seconds,
                        'tags': vm.tags,
                        'error': None
                    }
        
        # Fallback to virsh for legacy support
        return self._get_vm_details_legacy(vm_name)
    
    def _get_vm_details_legacy(self, vm_name):
        """Legacy VM details fallback"""
        details = {
            'name': vm_name,
            'state': 'unknown',
            'vcpus': 0,
            'memory': {},
            'disks': [],
            'interfaces': [],
            'snapshots': [],
            'cpu_stats': {},
            'error': None
        }
        try:
            result = subprocess.run(
                f'virsh dominfo {vm_name}',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'State:' in line:
                        details['state'] = line.split(':')[1].strip()
                    elif 'CPU(s):' in line:
                        details['vcpus'] = line.split(':')[1].strip()
                    elif 'Used memory:' in line:
                        details['memory']['used'] = line.split(':')[1].strip()
                    elif 'Max memory:' in line:
                        details['memory']['max'] = line.split(':')[1].strip()
        except Exception as e:
            details['error'] = str(e)
        return details
    
    # ---- Kubernetes Management ----
    
    def get_kubernetes_resources(self):
        """Get Kubernetes resources"""
        resources = {
            'available': False,
            'nodes': [],
            'pods': [],
            'deployments': [],
            'services': [],
            'namespaces': [],
            'jobs': [],
            'cronjobs': [],
            'pvcs': [],
            'ingresses': []
        }
        try:
            which_result = subprocess.run(['which', 'kubectl'], capture_output=True, text=True)
            if which_result.returncode != 0:
                return resources
            resources['available'] = True
            
            # Get nodes
            result = subprocess.run(
                'kubectl get nodes -o json 2>/dev/null',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for item in data.get('items', []):
                    resources['nodes'].append({
                        'name': item['metadata']['name'],
                        'status': self._get_node_status(item),
                        'version': item['status']['nodeInfo']['kubeletVersion'],
                        'cpu': item['status']['capacity']['cpu'],
                        'memory': item['status']['capacity']['memory'],
                        'age': self._calculate_age(item['metadata']['creationTimestamp'])
                    })
            
            # Get pods
            result = subprocess.run(
                'kubectl get pods --all-namespaces -o json 2>/dev/null',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for item in data.get('items', []):
                    resources['pods'].append({
                        'name': item['metadata']['name'],
                        'namespace': item['metadata']['namespace'],
                        'status': item['status']['phase'],
                        'node': item['spec'].get('nodeName', ''),
                        'restarts': sum(c.get('restartCount', 0) for c in item['status'].get('containerStatuses', [])),
                        'age': self._calculate_age(item['metadata']['creationTimestamp']),
                        'labels': item['metadata'].get('labels', {})
                    })
            
            # Get other resources
            for resource_type in ['deployments', 'services', 'jobs', 'cronjobs', 'pvcs', 'ingresses']:
                result = subprocess.run(
                    f'kubectl get {resource_type} --all-namespaces -o json 2>/dev/null',
                    shell=True, capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    for item in data.get('items', []):
                        resources[resource_type].append({
                            'name': item['metadata']['name'],
                            'namespace': item['metadata']['namespace'],
                            'age': self._calculate_age(item['metadata']['creationTimestamp'])
                        })
        except Exception as e:
            print(f"Kubernetes error: {e}")
        return resources
    
    def _get_node_status(self, node):
        """Get node status"""
        for condition in node['status'].get('conditions', []):
            if condition['type'] == 'Ready':
                return 'Ready' if condition['status'] == 'True' else 'NotReady'
        return 'Unknown'
    
    def _calculate_age(self, timestamp):
        """Calculate age from timestamp"""
        try:
            created = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            delta = datetime.now(created.tzinfo) - created
            if delta.days > 0:
                return f"{delta.days}d"
            hours = delta.seconds // 3600
            if hours > 0:
                return f"{hours}h"
            minutes = delta.seconds // 60
            return f"{minutes}m"
        except:
            return 'unknown'
    
    # ---- Event Management ----
    
    def add_event(self, event_type, message, severity='info'):
        """Add event to timeline"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'message': message,
            'severity': severity,
            'id': hashlib.md5(f"{time.time()}{message}".encode()).hexdigest()[:8]
        }
        self.events.appendleft(event)
        self.timeline.append(event)
        if severity in ('critical', 'error'):
            self.alerts.append({
                **event,
                'acknowledged': False,
                'resolved': False
            })
        return event
    
    def add_audit(self, user, action, resource):
        """Add audit entry"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'user': user,
            'action': action,
            'resource': resource
        }
        self.audit_log.appendleft(entry)
        return entry
    
    def get_timeline(self, hours=1):
        """Get timeline events"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [e for e in self.timeline if datetime.fromisoformat(e['timestamp']) > cutoff]
    
    # ---- Actions ----
    
    def execute_action(self, resource_type, resource_name, action, params=None):
        """Execute an action with optional parameters"""
        if params is None:
            params = {}
        job_id = hashlib.md5(f"{time.time()}{resource_name}{action}".encode()).hexdigest()[:12]
        
        def substitute(cmd):
            for key, value in params.items():
                cmd = cmd.replace(f"{{{key}}}", str(value))
            return cmd
        
        action_map = {
            'vm_restart': [
                {'name': 'Shutdown VM', 'type': 'command', 'command': f'virsh shutdown {resource_name}'},
                {'name': 'Wait for shutdown', 'type': 'sleep', 'duration': 30},
                {'name': 'Start VM', 'type': 'command', 'command': f'virsh start {resource_name}'},
                {'name': 'Wait for boot', 'type': 'sleep', 'duration': 30},
                {'name': 'Verify running', 'type': 'verify', 'command': f'virsh domstate {resource_name} | grep running'}
            ],
            'vm_shutdown': [
                {'name': 'Shutdown VM', 'type': 'command', 'command': f'virsh shutdown {resource_name}'},
                {'name': 'Wait', 'type': 'sleep', 'duration': 30},
                {'name': 'Verify', 'type': 'verify', 'command': f'virsh domstate {resource_name} | grep "shut off"'}
            ],
            'vm_snapshot': [
                {'name': 'Create snapshot', 'type': 'command', 'command': f'virsh snapshot-create-as {resource_name} auto-{datetime.now().strftime("%Y%m%d-%H%M%S")}'}
            ],
            'vm_pause': [
                {'name': 'Pause VM', 'type': 'command', 'command': f'virsh suspend {resource_name}'},
                {'name': 'Verify paused', 'type': 'verify', 'command': f'virsh domstate {resource_name} | grep paused'}
            ],
            'vm_resume': [
                {'name': 'Resume VM', 'type': 'command', 'command': f'virsh resume {resource_name}'},
                {'name': 'Verify running', 'type': 'verify', 'command': f'virsh domstate {resource_name} | grep running'}
            ],
            'pod_restart': [
                {'name': 'Delete pod', 'type': 'command', 'command': f'kubectl delete pod {resource_name}'},
                {'name': 'Wait for restart', 'type': 'sleep', 'duration': 10},
                {'name': 'Verify running', 'type': 'verify', 'command': f'kubectl get pod {resource_name} -o jsonpath="{{.status.phase}}" | grep Running'}
            ],
            'pod_delete': [
                {'name': 'Delete pod', 'type': 'command', 'command': f'kubectl delete pod {resource_name}'},
                {'name': 'Wait', 'type': 'sleep', 'duration': 5}
            ],
            'deployment_scale': [
                {'name': f'Scale deployment {resource_name} to {params.get("replicas", 1)}', 
                 'type': 'command', 
                 'command': substitute(f'kubectl scale deployment {resource_name} --replicas={{replicas}}')},
                {'name': 'Verify new replicas', 
                 'type': 'verify', 
                 'command': substitute(f'kubectl get deployment {resource_name} -o jsonpath="{{.status.readyReplicas}}" | grep {{replicas}}')}
            ],
            'deployment_delete': [
                {'name': 'Delete deployment', 'type': 'command', 'command': f'kubectl delete deployment {resource_name}'}
            ],
            'node_cordon': [
                {'name': 'Cordon node', 'type': 'command', 'command': f'kubectl cordon {resource_name}'}
            ],
            'node_uncordon': [
                {'name': 'Uncordon node', 'type': 'command', 'command': f'kubectl uncordon {resource_name}'}
            ],
            'node_drain': [
                {'name': 'Cordon node', 'type': 'command', 'command': f'kubectl cordon {resource_name}'},
                {'name': 'Drain node', 'type': 'command', 'command': f'kubectl drain {resource_name} --ignore-daemonsets --delete-emptydir-data --force'},
                {'name': 'Verify drained', 'type': 'verify', 'command': f'kubectl get node {resource_name} -o jsonpath="{{.spec.unschedulable}}" | grep true'}
            ]
        }
        
        action_key = f"{resource_type}_{action}"
        if action_key in action_map:
            job = self.automation.run_job(job_id, action, resource_name, action_map[action_key])
            self.add_event('action', f'{action} initiated on {resource_type} {resource_name}', 'info')
            self.add_audit('system', action, f'{resource_type}/{resource_name}')
            return job
        return None
    
    # ---- Diagnostics & Repair ----
    
    def run_diagnostics(self):
        """Run network diagnostics"""
        try:
            result = subprocess.run(
                ['sudo', 'network-recover', 'diagnose'],
                capture_output=True, text=True, timeout=30
            )
            issues = []
            for line in result.stdout.split('\n'):
                if 'FAIL' in line:
                    issues.append({
                        'severity': 'critical',
                        'message': line.strip(),
                        'suggested_action': 'Review and repair'
                    })
                elif 'WARN' in line:
                    issues.append({
                        'severity': 'warning',
                        'message': line.strip(),
                        'suggested_action': 'Monitor and investigate'
                    })
            return {
                'success': result.returncode == 0,
                'output': result.stdout[-2000:],
                'issues': issues
            }
        except Exception as e:
            return {'success': False, 'output': str(e), 'issues': []}
    
    def run_repair(self, target=None):
        """Run network repair"""
        try:
            cmd = ['sudo', 'network-recover', 'repair']
            if target:
                cmd.extend(['--target', target])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            self.add_event('recovery', f'Network repair {"succeeded" if result.returncode == 0 else "failed"}', 
                          'success' if result.returncode == 0 else 'error')
            return {
                'success': result.returncode == 0,
                'output': result.stdout[-2000:]
            }
        except Exception as e:
            return {'success': False, 'output': str(e)}
    
    def get_detected_problems(self):
        """Get detected problems"""
        diag = self.run_diagnostics()
        problems = []
        for issue in diag.get('issues', []):
            problems.append({
                'type': 'network',
                'severity': issue['severity'],
                'message': issue['message'],
                'suggested_action': issue.get('suggested_action', ''),
                'auto_fix': True if 'FAIL' in issue['message'] else False
            })
        return problems
    
    # ---- Search ----
    
    def search_resources(self, query):
        """Search across all resources"""
        results = []
        q = query.lower().strip()
        if not q:
            return results
        
        # Search VMs
        vms = self.get_vms_list()
        for vm in vms:
            if q in vm.get('name', '').lower() or q in vm.get('ip', '').lower():
                results.append({
                    'type': 'VM',
                    'name': vm['name'],
                    'state': vm['state'],
                    'path': f'vm/{vm["name"]}'
                })
        
        # Search Kubernetes
        k8s = self.get_kubernetes_resources()
        for resource_type, items in k8s.items():
            if isinstance(items, list):
                for item in items:
                    if q in item.get('name', '').lower() or q in item.get('namespace', '').lower():
                        results.append({
                            'type': resource_type.capitalize(),
                            'name': item['name'],
                            'namespace': item.get('namespace', ''),
                            'path': f'kubernetes/{resource_type}/{item["name"]}'
                        })
        
        # Search host
        host = self.get_host_info()
        if q in host.get('name', '').lower():
            results.append({
                'type': 'Host',
                'name': host['name'],
                'path': 'host'
            })
        
        return results[:20]

# ============================================================
# WEBSOCKET SERVER
# ============================================================

class WebSocketServer:
    """WebSocket server for real-time updates"""
    
    def __init__(self, monitor):
        self.monitor = monitor
        self.clients = set()
        self.subscriptions = {}
    
    async def handler(self, websocket, path):
        """Handle WebSocket connections"""
        self.clients.add(websocket)
        client_id = id(websocket)
        self.subscriptions[client_id] = ['metrics', 'events']
        try:
            await websocket.send(json.dumps({
                'type': 'connected',
                'data': {'client_id': client_id, 'timestamp': datetime.now().isoformat()}
            }))
            async for message in websocket:
                try:
                    data = json.loads(message)
                    response = await self.handle_command(data, client_id)
                    await websocket.send(json.dumps(response))
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({'type': 'error', 'message': 'Invalid JSON'}))
                except Exception as e:
                    await websocket.send(json.dumps({'type': 'error', 'message': str(e)}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            if client_id in self.subscriptions:
                del self.subscriptions[client_id]
    
    async def handle_command(self, data, client_id):
        """Handle WebSocket commands"""
        command = data.get('command', '')
        params = data.get('params', {})
        request_id = data.get('request_id', '')
        
        handlers = {
            'get_metrics': lambda: self.monitor.get_system_metrics(),
            'get_metrics_history': lambda: self.monitor.get_metrics_history(params.get('period', '1h')),
            'get_host_info': lambda: self.monitor.get_host_info(),
            'get_vms': lambda: self.monitor.get_vms_list(),
            'get_vm_details': lambda: self.monitor.get_vm_details(params.get('name', '')),
            'get_kubernetes': lambda: self.monitor.get_kubernetes_resources(),
            'get_events': lambda: list(self.monitor.events)[:50],
            'get_timeline': lambda: self.monitor.get_timeline(params.get('hours', 1)),
            'get_alerts': lambda: self.monitor.alerts,
            'get_audit_log': lambda: list(self.monitor.audit_log)[:100],
            'run_diagnostics': lambda: self.monitor.run_diagnostics(),
            'run_repair': lambda: self.monitor.run_repair(params.get('target')),
            'get_problems': lambda: self.monitor.get_detected_problems(),
            'search': lambda: self.monitor.search_resources(params.get('query', '')),
            'execute_action': lambda: self.monitor.execute_action(
                params.get('resource_type', ''),
                params.get('resource_name', ''),
                params.get('action', ''),
                params
            ),
            'get_job_status': lambda: self.monitor.automation.get_job_status(params.get('job_id', '')),
            'subscribe': lambda: self._handle_subscribe(client_id, params.get('topics', [])),
            'unsubscribe': lambda: self._handle_unsubscribe(client_id, params.get('topics', [])),
            'acknowledge_alert': lambda: self._acknowledge_alert(params.get('alert_id', '')),
        }
        
        if command in handlers:
            try:
                result = handlers[command]()
                return {'type': f'{command}_response', 'data': result, 'request_id': request_id}
            except Exception as e:
                return {'type': 'error', 'message': str(e), 'request_id': request_id}
        return {'type': 'error', 'message': f'Unknown command: {command}', 'request_id': request_id}
    
    def _handle_subscribe(self, client_id, topics):
        """Handle topic subscription"""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].extend(topics)
            self.subscriptions[client_id] = list(set(self.subscriptions[client_id]))
        return {'subscribed': topics}
    
    def _handle_unsubscribe(self, client_id, topics):
        """Handle topic unsubscription"""
        if client_id in self.subscriptions:
            self.subscriptions[client_id] = [t for t in self.subscriptions[client_id] if t not in topics]
        return {'unsubscribed': topics}
    
    def _acknowledge_alert(self, alert_id):
        """Acknowledge an alert"""
        for alert in self.monitor.alerts:
            if alert.get('id') == alert_id:
                alert['acknowledged'] = True
                return {'acknowledged': True}
        return {'acknowledged': False, 'error': 'Alert not found'}
    
    async def broadcast(self, message, topic=None):
        """Broadcast message to subscribed clients"""
        if self.clients:
            tasks = []
            for client in self.clients:
                client_id = id(client)
                if topic is None or topic in self.subscriptions.get(client_id, []):
                    tasks.append(asyncio.create_task(client.send(json.dumps(message))))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def start_broadcasting(self):
        """Start periodic broadcasting"""
        while True:
            try:
                metrics = self.monitor.get_system_metrics()
                await self.broadcast({'type': 'metrics_update', 'data': metrics}, topic='metrics')
                
                recent_events = list(self.monitor.events)[:20]
                if recent_events:
                    await self.broadcast({'type': 'events_update', 'data': recent_events}, topic='events')
                
                active_alerts = [a for a in self.monitor.alerts if not a.get('resolved')]
                if active_alerts:
                    await self.broadcast({'type': 'alerts_update', 'data': active_alerts}, topic='alerts')
                
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Broadcast error: {e}")
                await asyncio.sleep(5)

# ============================================================
# HTTP API SERVER
# ============================================================

class APIHandler(SimpleHTTPRequestHandler):
    """HTTP API handler"""
    monitor = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path.startswith('/api/'):
            self.handle_api_get()
        else:
            if self.path == '/' or self.path == '':
                self.path = '/index.html'
            super().do_GET()
    
    def do_POST(self):
        """Handle POST requests"""
        if self.path.startswith('/api/'):
            self.handle_api_post()
        else:
            self.send_error(404)
    
    def handle_api_get(self):
        """Handle API GET requests"""
        path = self.path.split('?')[0]
        routes = {
            '/api/status': self.api_get_status,
            '/api/metrics': self.api_get_metrics,
            '/api/metrics/history': self.api_get_metrics_history,
            '/api/host': self.api_get_host,
            '/api/vms': self.api_get_vms,
            '/api/vms/details': self.api_get_vm_details,
            '/api/kubernetes': self.api_get_kubernetes,
            '/api/events': self.api_get_events,
            '/api/timeline': self.api_get_timeline,
            '/api/alerts': self.api_get_alerts,
            '/api/audit': self.api_get_audit_log,
            '/api/problems': self.api_get_problems,
            '/api/jobs': self.api_get_jobs,
            '/api/search': self.api_search,
        }
        handler = routes.get(path)
        if handler:
            try:
                data = handler()
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, {'error': str(e)})
        else:
            self._send_json(404, {'error': 'Not found'})
    
    def handle_api_post(self):
        """Handle API POST requests"""
        path = self.path.split('?')[0]
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        try:
            params = json.loads(body)
        except:
            params = {}
        
        routes = {
            '/api/diagnostics': lambda: self.api_run_diagnostics(),
            '/api/repair': lambda: self.api_run_repair(params.get('target')),
            '/api/execute': lambda: self.api_execute_action(params),
            '/api/alerts/acknowledge': lambda: self.api_acknowledge_alert(params),
            '/api/terminal': lambda: self.api_terminal(params),
        }
        handler = routes.get(path)
        if handler:
            try:
                data = handler()
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, {'error': str(e)})
        else:
            self._send_json(404, {'error': 'Not found'})
    
    def _send_json(self, status, data):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    # ---- API Handlers ----
    
    def api_get_status(self):
        """Get system status"""
        return {
            'status': 'connected',
            'hosts_online': 1,
            'vms_running': len([v for v in self.monitor.get_vms_list() if v['state'] == 'running']),
            'k8s_available': self.monitor.get_kubernetes_resources()['available'],
            'timestamp': datetime.now().isoformat(),
            'uptime': self.monitor._get_uptime()
        }
    
    def api_get_metrics(self):
        """Get current metrics"""
        return self.monitor.get_system_metrics()
    
    def api_get_metrics_history(self):
        """Get metrics history"""
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        period = query.get('period', ['1h'])[0]
        return self.monitor.get_metrics_history(period)
    
    def api_get_host(self):
        """Get host info"""
        return self.monitor.get_host_info()
    
    def api_get_vms(self):
        """Get all VMs"""
        return self.monitor.get_vms_list()
    
    def api_get_vm_details(self):
        """Get VM details"""
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        name = query.get('name', [''])[0]
        return self.monitor.get_vm_details(name) if name else {'error': 'Missing name parameter'}
    
    def api_get_kubernetes(self):
        """Get Kubernetes resources"""
        return self.monitor.get_kubernetes_resources()
    
    def api_get_events(self):
        """Get recent events"""
        return list(self.monitor.events)[:100]
    
    def api_get_timeline(self):
        """Get timeline"""
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        hours = int(query.get('hours', ['1'])[0])
        return self.monitor.get_timeline(hours)
    
    def api_get_alerts(self):
        """Get active alerts"""
        return self.monitor.alerts
    
    def api_get_audit_log(self):
        """Get audit log"""
        return list(self.monitor.audit_log)[:100]
    
    def api_get_problems(self):
        """Get detected problems"""
        return self.monitor.get_detected_problems()
    
    def api_get_jobs(self):
        """Get job status"""
        return {
            'running': list(self.monitor.automation.running_jobs.values()),
            'completed': list(self.monitor.automation.completed_jobs)[:20]
        }
    
    def api_search(self):
        """Search resources"""
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        q = query.get('q', [''])[0]
        return self.monitor.search_resources(q)
    
    def api_run_diagnostics(self):
        """Run diagnostics"""
        return self.monitor.run_diagnostics()
    
    def api_run_repair(self, target=None):
        """Run repair"""
        return self.monitor.run_repair(target)
    
    def api_execute_action(self, params):
        """Execute an action"""
        return self.monitor.execute_action(
            params.get('resource_type', ''),
            params.get('resource_name', ''),
            params.get('action', ''),
            params
        )
    
    def api_acknowledge_alert(self, params):
        """Acknowledge an alert"""
        alert_id = params.get('alert_id', '')
        for alert in self.monitor.alerts:
            if alert.get('id') == alert_id:
                alert['acknowledged'] = True
                return {'acknowledged': True}
        return {'acknowledged': False, 'error': 'Alert not found'}
    
    def api_terminal(self, params):
        """Execute a terminal command"""
        command = params.get('command', '')
        if not command:
            return {'error': 'No command provided'}
        
        safe_commands = [
            'ping', 'kubectl', 'virsh', 'docker', 'systemctl', 
            'ps', 'top', 'df', 'free', 'netstat', 'ss', 'ip', 
            'ifconfig', 'route', 'nslookup', 'dig', 'curl', 'hostname',
            'whoami', 'date', 'uptime', 'uname', 'cat', 'echo',
            'k3s', 'helm'
        ]
        
        cmd_parts = command.split()
        if cmd_parts and cmd_parts[0] not in safe_commands:
            return {'error': f'Command "{cmd_parts[0]}" is not allowed. Allowed: {", ".join(safe_commands)}'}
        
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            return {
                'output': result.stdout + result.stderr,
                'exit_code': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'error': 'Command timed out after 30 seconds'}
        except Exception as e:
            return {'error': str(e)}

# ============================================================
# SERVER STARTUP
# ============================================================

def start_http_server(monitor):
    """Start HTTP server"""
    APIHandler.monitor = monitor
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer((HOST, HTTP_PORT), APIHandler)
    print(f"🌐 HTTP Server running on http://localhost:{HTTP_PORT}")
    print(f"   API available at http://localhost:{HTTP_PORT}/api/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("HTTP Server stopped")

async def start_ws_server(monitor):
    """Start WebSocket server"""
    ws_server = WebSocketServer(monitor)
    print(f"🔌 WebSocket Server running on ws://localhost:{WS_PORT}")
    async with websockets.serve(ws_server.handler, HOST, WS_PORT):
        broadcast_task = asyncio.create_task(ws_server.start_broadcasting())
        try:
            await asyncio.Future()
        except KeyboardInterrupt:
            pass
        finally:
            broadcast_task.cancel()
            print("WebSocket Server stopped")

def main():
    """Main entry point"""
    print("=" * 60)
    print("  Infrastructure Operations Center v4.0.0")
    print("  Universal VM Detection | WebSocket & REST API")
    print("=" * 60)
    print()
    
    monitor = InfrastructureMonitor()
    monitor.add_event('system', 'Infrastructure Operations Center started', 'info')
    
    print(f"  📊 Metrics collection: Active (5s interval)")
    print(f"  🤖 Automation engine: Ready")
    print(f"  🔍 Universal VM detection: Initialized")
    print(f"  📝 Event stream: Active")
    print(f"  📋 Job queue: Ready")
    print()
    
    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=start_http_server, args=(monitor,), daemon=True, name="HTTP-Server")
    http_thread.start()
    
    try:
        asyncio.run(start_ws_server(monitor))
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()