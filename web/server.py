#!/usr/bin/env python3
"""
Infrastructure Operations Center v3.1.0 - Three-Pane Operations Console
Full WebSocket-enabled server with integrated collectors, diagnostics, and repairs.
Uses parse_utils.py for structured data extraction from bash scripts.
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

# Import our parser module
from parse_utils import (
    OutputParser, 
    Status, 
    DiagnosticResult,
    NetworkInterface,
    VMData, 
    DNSConfig, 
    NetworkManagerStatus,
    collect_vm_metrics_ssh
)

# Configuration
HOST = '0.0.0.0'
HTTP_PORT = 9876
WS_PORT = 9877
STATIC_DIR = Path(__file__).parent / 'static'

# Base paths - web/ is one level up from the script's parent
BASE_DIR = Path(__file__).parent.parent  # network-recover/
COLLECTORS_DIR = BASE_DIR / 'collectors'
DIAGNOSTICS_DIR = BASE_DIR / 'diagnostics'
REPAIRS_DIR = BASE_DIR / 'repairs'

# ============================================================
# AUTOMATION ENGINE (unchanged - already good)
# ============================================================

class AutomationEngine:
    """Rule-based automation engine with job queue tracking"""
    
    def __init__(self):
        self.automations = []
        self.job_queue = deque()
        self.completed_jobs = deque(maxlen=100)
        self.running_jobs = {}
        
    def add_automation(self, name, trigger, actions):
        self.automations.append({
            'name': name,
            'trigger': trigger,
            'actions': actions,
            'enabled': True
        })
    
    def run_job(self, job_id, job_type, target, steps):
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
                            step['command'], 
                            shell=True, 
                            capture_output=True, 
                            text=True,
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
                                if job_id in self.running_jobs:
                                    del self.running_jobs[job_id]
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
                            step['command'],
                            shell=True,
                            capture_output=True,
                            text=True,
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
                        if job_id in self.running_jobs:
                            del self.running_jobs[job_id]
                        return jobs_processed
                except Exception as e:
                    job['log'].append({
                        'timestamp': datetime.now().isoformat(),
                        'message': f"✗ Error: {str(e)}",
                        'level': 'error'
                    })
            
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
            if job_id in self.running_jobs:
                del self.running_jobs[job_id]
        
        return jobs_processed
    
    def get_job_status(self, job_id):
        if job_id in self.running_jobs:
            return self.running_jobs[job_id]
        for job in self.completed_jobs:
            if job['id'] == job_id:
                return job
        return None


# ============================================================
# INFRASTRUCTURE MONITOR (REWRITTEN with parser integration)
# ============================================================

class InfrastructureMonitor:
    """Complete monitoring engine with integrated collectors and diagnostics"""
    
    def __init__(self):
        self.automation = AutomationEngine()
        self.metrics_history = deque(maxlen=720)
        self.events = deque(maxlen=500)
        self.alerts = []
        self.audit_log = deque(maxlen=1000)
        self.timeline = deque(maxlen=200)
        self.last_update = time.time()
        
        # VM data cache
        self._vms_cache = None
        self._vms_cache_time = 0
        
        # Known VM IPs for SSH-based metrics
        self.known_vm_ips = {
            'k8s-node-01': '10.0.0.21',
            'k8s-node-02': '10.0.0.22',
            'k8s-node-03': '10.0.0.23'
        }
        
        self._init_automations()
        self._clean_old_files()
        
        threading.Thread(target=self._collect_metrics_loop, daemon=True).start()
        threading.Thread(target=self._process_jobs_loop, daemon=True).start()
        threading.Thread(target=self._auto_clean_loop, daemon=True).start()
    
    def _init_automations(self):
        self.automation.add_automation(
            "Pod CrashLoop Recovery",
            {"type": "pod_status", "condition": "CrashLoopBackOff"},
            [
                {"name": "Restart pod", "type": "command", "command": "kubectl delete pod {target}"},
                {"name": "Wait for restart", "type": "sleep", "duration": 30},
                {"name": "Check status", "type": "verify", "command": "kubectl get pod {target} -o jsonpath='{.status.phase}' | grep Running"}
            ]
        )
    
    def _clean_old_files(self, days=7):
        try:
            cutoff = time.time() - (days * 86400)
            cleaned = 0
            for dir_path in ['/var/log/network-events', '/var/lib/network-recover/snapshots']:
                if os.path.exists(dir_path):
                    for f in glob.glob(os.path.join(dir_path, '*.log')):
                        try:
                            if os.path.getmtime(f) < cutoff:
                                os.remove(f)
                                cleaned += 1
                        except:
                            pass
            if cleaned > 0:
                print(f"🧹 Auto-cleaned {cleaned} old files")
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    def _auto_clean_loop(self):
        while True:
            time.sleep(3600)
            self._clean_old_files(days=7)
    
    def _collect_metrics_loop(self):
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
        while True:
            try:
                self.automation.process_jobs()
                time.sleep(1)
            except:
                time.sleep(5)
    
    # ============================================================
    # SYSTEM METRICS (psutil-based - already good)
    # ============================================================
    
    def get_system_metrics(self):
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        
        # Calculate network speed from history
        prev = self.metrics_history[-1] if self.metrics_history else None
        rx_mbps = 0
        tx_mbps = 0
        if prev and 'network_rx_bytes' in prev:
            elapsed = time.time() - self.last_update
            if elapsed > 0:
                rx_mbps = round((net.bytes_recv - prev['network_rx_bytes']) * 8 / (elapsed * 1_000_000), 1)
                tx_mbps = round((net.bytes_sent - prev['network_tx_bytes']) * 8 / (elapsed * 1_000_000), 1)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'cpu': cpu_percent,
            'cpu_count': psutil.cpu_count(),
            'ram': mem.percent,
            'ram_used_gb': round(mem.used / (1024**3), 1),
            'ram_total_gb': round(mem.total / (1024**3), 1),
            'disk': disk.percent,
            'disk_used_gb': round(disk.used / (1024**3), 1),
            'disk_total_gb': round(disk.total / (1024**3), 1),
            'network_rx_bytes': net.bytes_recv,
            'network_tx_bytes': net.bytes_sent,
            'network_rx_mbps': rx_mbps,
            'network_tx_mbps': tx_mbps,
            'network_speed_mbps': round(rx_mbps + tx_mbps, 1),
            'load_avg_1m': psutil.getloadavg()[0],
            'load_avg_5m': psutil.getloadavg()[1],
            'load_avg_15m': psutil.getloadavg()[2],
            'processes': len(psutil.pids()),
            'swap': psutil.swap_memory().percent,
            'uptime': self._get_uptime(),
            'uptime_seconds': time.time() - psutil.boot_time(),
            'os': os.uname().sysname if hasattr(os, 'uname') else 'Linux',
            'name': socket.gethostname()
        }
    
    def _get_uptime(self):
        uptime_seconds = time.time() - psutil.boot_time()
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    
    def get_metrics_history(self, period='1h'):
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
            'network_mbps': [m.get('network_speed_mbps', 0) for m in sampled]
        }
    
    def get_host_info(self):
        m = self.get_system_metrics()
        return {
            'name': m['name'],
            'cpu_percent': m['cpu'],
            'cpu_count': m['cpu_count'],
            'ram_percent': m['ram'],
            'ram_total_gb': m['ram_total_gb'],
            'ram_used_gb': m['ram_used_gb'],
            'disk_percent': m['disk'],
            'disk_total_gb': m['disk_total_gb'],
            'disk_used_gb': m['disk_used_gb'],
            'network_speed_mbps': m['network_speed_mbps'],
            'status': 'online',
            'uptime': m['uptime'],
            'load_avg_1m': m['load_avg_1m'],
            'processes': m['processes'],
            'swap': m['swap'],
            'os': m['os']
        }
    
    # ============================================================
    # COLLECTOR INTEGRATION (NEW - uses parse_utils.py)
    # ============================================================
    
    def run_collector(self, name: str) -> dict:
        """Run a collector script and return parsed structured data"""
        script_path = COLLECTORS_DIR / name
        if not script_path.exists():
            return {'error': f'Collector {name} not found at {script_path}'}
        
        try:
            result = subprocess.run(
                [str(script_path)],
                capture_output=True,
                text=True,
                timeout=15
            )
            return OutputParser.run_collector(str(COLLECTORS_DIR), name)
        except Exception as e:
            return {'error': str(e), 'raw': getattr(result, 'stdout', '')}
    
    def get_network_interfaces(self) -> dict:
        """Get parsed network interface data from iproute2 collector"""
        return self.run_collector('iproute2')
    
    def get_network_manager_status(self) -> dict:
        """Get parsed NetworkManager status from nmcli collector"""
        return self.run_collector('nmcli')
    
    def get_dns_config(self) -> dict:
        """Get parsed DNS configuration from resolvectl collector"""
        return self.run_collector('resolvectl')
    
    def get_system_logs(self) -> list:
        """Get parsed journal logs from journalctl collector"""
        return self.run_collector('journalctl')
    
    # ============================================================
    # VM MANAGEMENT (REWRITTEN with libvirt collector + SSH)
    # ============================================================
    
    def get_vms_list(self, force_refresh=False) -> list:
        """Get VMs with full metrics using libvirt collector and SSH"""
        
        cache_ttl = 30 if not force_refresh else 0
        
        if self._vms_cache and (time.time() - self._vms_cache_time) < cache_ttl:
            return self._vms_cache
        
        vms = []
        
        # 1. Get VMs from libvirt collector (parsed)
        libvirt_data = self.run_collector('libvirt')
        
        # 2. For each VM, enrich with SSH metrics
        for vm_name, vm_ip in self.known_vm_ips.items():
            # Get SSH-based metrics
            ssh_metrics = collect_vm_metrics_ssh(vm_ip, ssh_user='devcyp')
            
            # Determine state
            state = 'running' if ssh_metrics.get('reachable') else 'unknown'
            
            vm_data = {
                'name': vm_name,
                'state': state,
                'ip': vm_ip,
                'hypervisor': 'libvirt',
                'id': None,
                # CPU
                'cpu': f"{ssh_metrics.get('cpu', 0):.0f}%" if ssh_metrics.get('reachable') else 'N/A',
                # RAM
                'ram': ssh_metrics.get('memory', {}).get('used', 'N/A') if ssh_metrics.get('reachable') else 'N/A',
                'ram_percent': ssh_metrics.get('memory', {}).get('percent', 0),
                # Disk
                'disk': ssh_metrics.get('disk', {}).get('used', 'N/A') if ssh_metrics.get('reachable') else 'N/A',
                'disk_percent': ssh_metrics.get('disk', {}).get('percent', 0),
                # Swap
                'swap': ssh_metrics.get('swap', {}).get('used', '0') if ssh_metrics.get('reachable') else 'N/A',
                'swap_percent': ssh_metrics.get('swap', {}).get('percent', 0),
                # Load
                'load': ssh_metrics.get('load', {}).get('1m', 0),
                # Uptime
                'uptime': ssh_metrics.get('uptime', 'N/A')
            }
            vms.append(vm_data)
        
        # Cache results
        self._vms_cache = vms
        self._vms_cache_time = time.time()
        
        return vms
    
    def get_vm_details(self, vm_name: str) -> dict:
        """Get comprehensive VM details for drawer view"""
        details = {
            'name': vm_name,
            'state': 'unknown',
            'vcpus': 0,
            'memory': {'used': 'N/A', 'max': 'N/A'},
            'disks': [],
            'interfaces': [],
            'snapshots': [],
            'cpu_stats': {},
            'pods': [],
            'error': None
        }
        
        # Try virsh dominfo
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
                        try:
                            details['vcpus'] = int(line.split(':')[1].strip())
                        except:
                            pass
                    elif 'Used memory:' in line:
                        details['memory']['used'] = line.split(':')[1].strip()
                    elif 'Max memory:' in line:
                        details['memory']['max'] = line.split(':')[1].strip()
        except:
            pass
        
        # Get SSH metrics if VM has known IP
        if vm_name in self.known_vm_ips:
            ip = self.known_vm_ips[vm_name]
            ssh_metrics = collect_vm_metrics_ssh(ip, ssh_user='devcyp')
            if ssh_metrics.get('reachable'):
                details['state'] = 'running'
                details['memory'] = ssh_metrics.get('memory', details['memory'])
                details['cpu_usage'] = ssh_metrics.get('cpu', 0)
                details['load'] = ssh_metrics.get('load', {})
                details['uptime'] = ssh_metrics.get('uptime', '')
        
        # Get snapshots
        try:
            result = subprocess.run(
                f'virsh snapshot-list {vm_name} --name',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                details['snapshots'] = [s.strip() for s in result.stdout.split('\n') if s.strip()]
        except:
            pass
        
        # Get disks
        try:
            result = subprocess.run(
                f'virsh domblklist {vm_name} --details',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n')[2:]:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 3:
                            details['disks'].append({
                                'type': parts[0],
                                'device': parts[1],
                                'target': parts[2],
                                'source': parts[3] if len(parts) > 3 else ''
                            })
        except:
            pass
        
        # Get interfaces
        try:
            result = subprocess.run(
                f'virsh domiflist {vm_name}',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n')[2:]:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 5:
                            details['interfaces'].append({
                                'type': parts[1],
                                'source': parts[2],
                                'model': parts[3],
                                'mac': parts[4]
                            })
        except:
            pass
        
        # Get pods running on this VM (if it's a k8s node)
        k8s = self.get_kubernetes_resources()
        if k8s['available']:
            details['pods'] = [
                {'name': p['name'], 'namespace': p['namespace'], 'status': p['status']}
                for p in k8s.get('pods', [])
                if p.get('node') == vm_name
            ]
        
        return details
    
    # ============================================================
    # KUBERNETES (unchanged - already good)
    # ============================================================
    
    def get_kubernetes_resources(self):
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
            
            # Nodes
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
            
            # Pods
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
                        'age': self._calculate_age(item['metadata']['creationTimestamp'])
                    })
            
            # Other resources
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
        for condition in node['status'].get('conditions', []):
            if condition['type'] == 'Ready':
                return 'Ready' if condition['status'] == 'True' else 'NotReady'
        return 'Unknown'
    
    def _calculate_age(self, timestamp):
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
    
    # ============================================================
    # DIAGNOSTICS (REWRITTEN - uses parse_utils.py + all 10 layers)
    # ============================================================
    
    def run_diagnostics(self, diagnostic_type='network', target=None):
        """
        Run diagnostics using the diagnostic scripts.
        Returns structured results from parse_utils.
        """
        try:
            if diagnostic_type == 'network' or diagnostic_type == 'all':
                # Run all 10 diagnostic layers
                results = OutputParser.run_all_diagnostics(
                    str(DIAGNOSTICS_DIR),
                    interface=target or None,
                    bridge='br0'  # Adjust if your bridge name differs
                )
                
                # Convert to JSON
                diag_json = OutputParser.diagnostics_to_json(results)
                
                # Generate human-readable output for the network view
                output_lines = []
                layer_names = [
                    "PHYSICAL LAYER", "INTERFACE LAYER", "IP LAYER", "ROUTING LAYER",
                    "GATEWAY LAYER", "DNS LAYER", "HTTPS LAYER", "NETWORKMANAGER LAYER",
                    "BRIDGE LAYER", "KVM LAYER"
                ]
                
                for i, result in enumerate(results):
                    layer_num = i + 1
                    name = layer_names[i] if i < len(layer_names) else f"LAYER {layer_num}"
                    
                    emoji = "✅" if result.status == Status.PASS else "❌" if result.status == Status.FAIL else "⚠️"
                    output_lines.append(f"\n{'='*50}")
                    output_lines.append(f"  LAYER {layer_num}: {name}")
                    output_lines.append(f"  {emoji} {result.message}")
                    output_lines.append(f"{'='*50}")
                    
                    # Add details
                    for key, value in result.details.items():
                        if value is not None and value != '':
                            if isinstance(value, dict):
                                output_lines.append(f"  📌 {key}: {json.dumps(value)}")
                            elif isinstance(value, list):
                                output_lines.append(f"  📌 {key}: {', '.join(str(v) for v in value)}")
                            else:
                                output_lines.append(f"  📌 {key}: {value}")
                
                # Extract issues from failed layers
                issues = []
                for result in results:
                    if result.status == Status.FAIL:
                        issues.append({
                            'severity': 'critical',
                            'message': f"{result.layer.upper()}: {result.message}",
                            'suggested_action': f"Check {result.layer} configuration"
                        })
                    elif result.status == Status.WARN:
                        issues.append({
                            'severity': 'warning',
                            'message': f"{result.layer.upper()}: {result.message}",
                            'suggested_action': f"Monitor {result.layer}"
                        })
                
                return {
                    'success': diag_json['summary']['overall_status'] == 'pass',
                    'output': '\n'.join(output_lines),
                    'issues': issues,
                    'structured': diag_json
                }
            
            elif diagnostic_type == 'vm' and target:
                # Run VM-specific diagnostics
                output = subprocess.run(
                    [str(DIAGNOSTICS_DIR / 'kvm')],
                    capture_output=True, text=True, timeout=10
                )
                return {
                    'success': output.returncode == 0,
                    'output': output.stdout[-2000:],
                    'issues': []
                }
            
            elif diagnostic_type == 'kubernetes':
                # Kubernetes health check
                output_lines = []
                issues = []
                k8s = self.get_kubernetes_resources()
                
                if not k8s['available']:
                    output_lines.append("❌ kubectl not available")
                    issues.append({'severity': 'critical', 'message': 'kubectl not available'})
                else:
                    not_ready = [n for n in k8s['nodes'] if n['status'] != 'Ready']
                    failing_pods = [p for p in k8s['pods'] if p['status'] not in ['Running', 'Succeeded']]
                    
                    output_lines.append(f"✅ kubectl available")
                    output_lines.append(f"📊 Nodes: {len(k8s['nodes'])} total, {len(not_ready)} not ready")
                    output_lines.append(f"📊 Pods: {len(k8s['pods'])} total, {len(failing_pods)} not running")
                    
                    if not_ready:
                        for node in not_ready:
                            msg = f"Node {node['name']} is {node['status']}"
                            output_lines.append(f"❌ {msg}")
                            issues.append({'severity': 'critical', 'message': msg})
                    
                    if failing_pods:
                        for pod in failing_pods[:10]:
                            msg = f"Pod {pod['namespace']}/{pod['name']} is {pod['status']}"
                            output_lines.append(f"⚠️ {msg}")
                            issues.append({'severity': 'warning', 'message': msg})
                
                return {
                    'success': len(issues) == 0,
                    'output': '\n'.join(output_lines),
                    'issues': issues
                }
            
            else:
                # Fallback to network-recover diagnose
                result = subprocess.run(
                    ['sudo', 'network-recover', 'diagnose'],
                    capture_output=True, text=True, timeout=30
                )
                issues = []
                for line in result.stdout.split('\n'):
                    if 'FAIL' in line:
                        issues.append({'severity': 'critical', 'message': line.strip()})
                    elif 'WARN' in line:
                        issues.append({'severity': 'warning', 'message': line.strip()})
                return {
                    'success': result.returncode == 0,
                    'output': result.stdout[-2000:],
                    'issues': issues
                }
                
        except Exception as e:
            return {
                'success': False,
                'output': str(e),
                'issues': [{'severity': 'critical', 'message': str(e)}]
            }
    
    # ============================================================
    # REPAIRS (REWRITTEN - uses modular repair scripts)
    # ============================================================
    
    def run_repair(self, target=None):
        """Run repairs using the modular repair scripts"""
        try:
            repair_scripts = {
                'bridge': REPAIRS_DIR / 'bridge',
                'dhcp': REPAIRS_DIR / 'dhcp',
                'dns': REPAIRS_DIR / 'dns',
                'interface': REPAIRS_DIR / 'interface',
                'nm': REPAIRS_DIR / 'nm',
                'routing': REPAIRS_DIR / 'routing',
            }
            
            output_lines = []
            all_success = True
            
            # If specific target, run only that repair
            if target and target in repair_scripts:
                script = repair_scripts[target]
                result = subprocess.run(
                    [str(script)],
                    capture_output=True, text=True, timeout=30
                )
                output_lines.append(result.stdout)
                if result.returncode != 0:
                    all_success = False
            else:
                # Run all repairs
                for name, script in repair_scripts.items():
                    if script.exists():
                        output_lines.append(f"\n--- Repair: {name} ---")
                        result = subprocess.run(
                            [str(script)],
                            capture_output=True, text=True, timeout=30
                        )
                        output_lines.append(result.stdout)
                        if result.returncode != 0:
                            all_success = False
            
            output = '\n'.join(output_lines)
            
            self.add_event(
                'recovery',
                f"Repair {'succeeded' if all_success else 'partially failed'}",
                'success' if all_success else 'error'
            )
            
            return {
                'success': all_success,
                'output': output[-2000:]
            }
            
        except Exception as e:
            return {'success': False, 'output': str(e)}
    
    def get_detected_problems(self):
        """Get detected problems from diagnostics"""
        diag = self.run_diagnostics()
        problems = []
        for issue in diag.get('issues', []):
            problems.append({
                'type': 'network',
                'severity': issue['severity'],
                'message': issue['message'],
                'suggested_action': issue.get('suggested_action', ''),
                'auto_fix': 'FAIL' in issue.get('message', '')
            })
        return problems
    
    # ============================================================
    # EVENTS & SEARCH (unchanged)
    # ============================================================
    
    def add_event(self, event_type, message, severity='info'):
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
            self.alerts.append({**event, 'acknowledged': False, 'resolved': False})
        return event
    
    def add_audit(self, user, action, resource):
        entry = {
            'timestamp': datetime.now().isoformat(),
            'user': user,
            'action': action,
            'resource': resource
        }
        self.audit_log.appendleft(entry)
        return entry
    
    def get_timeline(self, hours=1):
        cutoff = datetime.now() - timedelta(hours=hours)
        return [e for e in self.timeline if datetime.fromisoformat(e['timestamp']) > cutoff]
    
    def search_resources(self, query):
        results = []
        q = query.lower().strip()
        if not q:
            return results
        
        vms = self.get_vms_list()
        for vm in vms:
            if q in vm.get('name', '').lower() or q in vm.get('ip', '').lower():
                results.append({
                    'type': 'VM',
                    'name': vm['name'],
                    'state': vm['state'],
                    'path': f'vm/{vm["name"]}'
                })
        
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
        
        host = self.get_host_info()
        if q in host.get('name', '').lower():
            results.append({
                'type': 'Host',
                'name': host['name'],
                'path': 'host'
            })
        
        return results[:20]
    
    # ============================================================
    # ACTIONS (unchanged - already comprehensive)
    # ============================================================
    
    def execute_action(self, resource_type, resource_name, action, params=None):
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
                {'name': 'Delete pod', 'type': 'command', 'command': f'kubectl delete pod {resource_name}'}
            ],
            'deployment_scale': [
                {'name': f'Scale deployment {resource_name}', 'type': 'command', 
                 'command': substitute(f'kubectl scale deployment {resource_name} --replicas={{replicas}}')},
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
                {'name': 'Drain node', 'type': 'command', 'command': f'kubectl drain {resource_name} --ignore-daemonsets --delete-emptydir-data --force'}
            ]
        }
        
        action_key = f"{resource_type}_{action}"
        if action_key in action_map:
            job = self.automation.run_job(job_id, action, resource_name, action_map[action_key])
            self.add_event('action', f'{action} initiated on {resource_type} {resource_name}', 'info')
            self.add_audit('system', action, f'{resource_type}/{resource_name}')
            return job
        return None


# ============================================================
# WEBSOCKET SERVER (updated with new command handlers)
# ============================================================

class WebSocketServer:
    def __init__(self, monitor):
        self.monitor = monitor
        self.clients = set()
        self.subscriptions = {}
    
    async def handler(self, websocket, path):
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
        command = data.get('command', '')
        params = data.get('params', {})
        request_id = data.get('request_id', '')
        
        handlers = {
            # Metrics
            'get_metrics': lambda: self.monitor.get_system_metrics(),
            'get_metrics_history': lambda: self.monitor.get_metrics_history(params.get('period', '1h')),
            'get_host_info': lambda: self.monitor.get_host_info(),
            
            # VMs
            'get_vms': lambda: self.monitor.get_vms_list(),
            'get_vm_details': lambda: self.monitor.get_vm_details(params.get('name', '')),
            
            # Kubernetes
            'get_kubernetes': lambda: self.monitor.get_kubernetes_resources(),
            
            # NEW: Collector-based endpoints
            'get_network_interfaces': lambda: self.monitor.get_network_interfaces(),
            'get_network_manager': lambda: self.monitor.get_network_manager_status(),
            'get_dns_config': lambda: self.monitor.get_dns_config(),
            'get_system_logs': lambda: self.monitor.get_system_logs(),
            
            # Diagnostics (now uses parse_utils)
            'run_diagnostics': lambda: self.monitor.run_diagnostics(
                params.get('type', 'network'),
                params.get('target')
            ),
            'run_repair': lambda: self.monitor.run_repair(params.get('target')),
            'get_problems': lambda: self.monitor.get_detected_problems(),
            
            # Events & Alerts
            'get_events': lambda: list(self.monitor.events)[:50],
            'get_timeline': lambda: self.monitor.get_timeline(params.get('hours', 1)),
            'get_alerts': lambda: self.monitor.alerts,
            'get_audit_log': lambda: list(self.monitor.audit_log)[:100],
            
            # Search & Actions
            'search': lambda: self.monitor.search_resources(params.get('query', '')),
            'execute_action': lambda: self.monitor.execute_action(
                params.get('resource_type', ''),
                params.get('resource_name', ''),
                params.get('action', ''),
                params
            ),
            'get_job_status': lambda: self.monitor.automation.get_job_status(params.get('job_id', '')),
            
            # Subscriptions
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
        if client_id in self.subscriptions:
            self.subscriptions[client_id].extend(topics)
            self.subscriptions[client_id] = list(set(self.subscriptions[client_id]))
        return {'subscribed': topics}
    
    def _handle_unsubscribe(self, client_id, topics):
        if client_id in self.subscriptions:
            self.subscriptions[client_id] = [t for t in self.subscriptions[client_id] if t not in topics]
        return {'unsubscribed': topics}
    
    def _acknowledge_alert(self, alert_id):
        for alert in self.monitor.alerts:
            if alert.get('id') == alert_id:
                alert['acknowledged'] = True
                return {'acknowledged': True}
        return {'acknowledged': False, 'error': 'Alert not found'}
    
    async def broadcast(self, message, topic=None):
        if self.clients:
            tasks = []
            for client in self.clients:
                client_id = id(client)
                if topic is None or topic in self.subscriptions.get(client_id, []):
                    tasks.append(asyncio.create_task(client.send(json.dumps(message))))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def start_broadcasting(self):
        while True:
            try:
                metrics = self.monitor.get_system_metrics()
                await self.broadcast({'type': 'metrics_update', 'data': metrics}, topic='metrics')
                recent_events = list(self.monitor.events)[:20]
                if recent_events:
                    await self.broadcast({'type': 'events_update', 'data': recent_events}, topic='events')
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Broadcast error: {e}")
                await asyncio.sleep(5)


# ============================================================
# HTTP API SERVER (unchanged - already comprehensive)
# ============================================================

class APIHandler(SimpleHTTPRequestHandler):
    monitor = None
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)
    
    def do_GET(self):
        if self.path.startswith('/api/'):
            self.handle_api_get()
        else:
            if self.path == '/' or self.path == '':
                self.path = '/index.html'
            super().do_GET()
    
    def do_POST(self):
        if self.path.startswith('/api/'):
            self.handle_api_post()
        else:
            self.send_error(404)
    
    def handle_api_get(self):
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
            '/api/network/layers': self.api_get_network_layers,
            '/api/network/interfaces': self.api_get_network_interfaces,
            '/api/network/dns': self.api_get_dns_config,
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
        path = self.path.split('?')[0]
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        try:
            params = json.loads(body)
        except:
            params = {}
        
        routes = {
            '/api/diagnostics': lambda: self.api_run_diagnostics(params),
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
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    # ---- API Handlers ----
    def api_get_status(self):
        vms = self.monitor.get_vms_list()
        k8s = self.monitor.get_kubernetes_resources()
        return {
            'status': 'connected',
            'hosts_online': 1,
            'host': socket.gethostname(),
            'vms_running': len([v for v in vms if v['state'] == 'running']),
            'k8s_available': k8s['available'],
            'timestamp': datetime.now().isoformat(),
            'uptime': self.monitor._get_uptime()
        }
    
    def api_get_metrics(self):
        return self.monitor.get_system_metrics()
    
    def api_get_metrics_history(self):
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        period = query.get('period', ['1h'])[0]
        return self.monitor.get_metrics_history(period)
    
    def api_get_host(self):
        return self.monitor.get_host_info()
    
    def api_get_vms(self):
        return self.monitor.get_vms_list()
    
    def api_get_vm_details(self):
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        name = query.get('name', [''])[0]
        return self.monitor.get_vm_details(name) if name else {'error': 'Missing name parameter'}
    
    def api_get_kubernetes(self):
        return self.monitor.get_kubernetes_resources()
    
    def api_get_events(self):
        return list(self.monitor.events)[:100]
    
    def api_get_timeline(self):
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        hours = int(query.get('hours', ['1'])[0])
        return self.monitor.get_timeline(hours)
    
    def api_get_alerts(self):
        return self.monitor.alerts
    
    def api_get_audit_log(self):
        return list(self.monitor.audit_log)[:100]
    
    def api_get_problems(self):
        return self.monitor.get_detected_problems()
    
    def api_get_jobs(self):
        return {
            'running': list(self.monitor.automation.running_jobs.values()),
            'completed': list(self.monitor.automation.completed_jobs)[:20]
        }
    
    def api_search(self):
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        q = query.get('q', [''])[0]
        return self.monitor.search_resources(q)
    
    def api_get_network_layers(self):
        """Get structured network diagnostic results"""
        diag = self.monitor.run_diagnostics('network')
        return diag.get('structured', {})
    
    def api_get_network_interfaces(self):
        """Get parsed network interfaces from iproute2"""
        return self.monitor.get_network_interfaces()
    
    def api_get_dns_config(self):
        """Get parsed DNS configuration"""
        return self.monitor.get_dns_config()
    
    def api_run_diagnostics(self, params=None):
        if params is None:
            params = {}
        return self.monitor.run_diagnostics(
            params.get('type', 'network'),
            params.get('target')
        )
    
    def api_run_repair(self, target=None):
        return self.monitor.run_repair(target)
    
    def api_execute_action(self, params):
        return self.monitor.execute_action(
            params.get('resource_type', ''),
            params.get('resource_name', ''),
            params.get('action', ''),
            params
        )
    
    def api_acknowledge_alert(self, params):
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
            'k3s', 'kubectl', 'helm'
        ]
        
        cmd_parts = command.split()
        if cmd_parts and cmd_parts[0] not in safe_commands:
            return {'error': f'Command "{cmd_parts[0]}" is not allowed'}
        
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

async def start_ws_server(monitor):
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

def main():
    print("=" * 60)
    print("  Infrastructure Operations Center v3.1.0")
    print("  Integrated with collectors, diagnostics & repairs")
    print("=" * 60)
    print(f"  📁 Collectors: {COLLECTORS_DIR}")
    print(f"  📁 Diagnostics: {DIAGNOSTICS_DIR}")
    print(f"  📁 Repairs: {REPAIRS_DIR}")
    print()
    
    monitor = InfrastructureMonitor()
    monitor.add_event('system', 'Infrastructure Operations Center started', 'info')
    
    print(f"  📊 Metrics collection: Active (5s interval)")
    print(f"  🤖 Automation engine: Ready")
    print(f"  🔍 Diagnostics: 10 layers available")
    print(f"  🔧 Repairs: 6 repair modules")
    print()
    
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