#!/usr/bin/env python3
"""
Infrastructure Operations Center v3.0.0 - Three-Pane Operations Console
Full WebSocket-enabled server with automation engine, job queue, and timeline
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
import glob  # ← ADD THIS for file pattern matching

# Configuration
HOST = '0.0.0.0'
HTTP_PORT = 9876
WS_PORT = 9877
STATIC_DIR = Path(__file__).parent / 'static'

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
        """Process queued jobs - call this in a loop"""
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
                    if step.get('on_failure') == 'stop':
                        job['status'] = 'failed'
                        job['end_time'] = datetime.now().isoformat()
                        jobs_processed.append(job)
                        self.completed_jobs.appendleft(job)
                        if job_id in self.running_jobs:
                            del self.running_jobs[job_id]
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
            if job_id in self.running_jobs:
                del self.running_jobs[job_id]
        
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
    """Complete monitoring engine with metrics, events, timeline, and automation"""
    
    def __init__(self):
        self.automation = AutomationEngine()
        # Reduced history sizes for better performance
        self.metrics_history = deque(maxlen=720)   # 1 hour at 5s intervals
        self.events = deque(maxlen=500)            # Last 500 events
        self.alerts = []
        self.audit_log = deque(maxlen=1000)        # Last 1000 audit entries
        self.timeline = deque(maxlen=200)          # Last 200 timeline events
        self.last_update = time.time()
        
        # Initialize default automations
        self._init_automations()
        
        # Auto-clean old files on startup
        self._clean_old_files()
        
        # Start background tasks
        threading.Thread(target=self._collect_metrics_loop, daemon=True).start()
        threading.Thread(target=self._process_jobs_loop, daemon=True).start()
        threading.Thread(target=self._auto_clean_loop, daemon=True).start()  # ← ADD THIS
    
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
            
            # Clean diagnostic logs
            log_dir = "/var/log/network-events"
            if os.path.exists(log_dir):
                for f in glob.glob(os.path.join(log_dir, "*.log")):
                    try:
                        if os.path.getmtime(f) < cutoff:
                            os.remove(f)
                            cleaned_count += 1
                    except:
                        pass
            
            # Clean snapshot files
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
                time.sleep(3600)  # 1 hour
                self._clean_old_files(days=7)  # Keep 7 days
            except:
                time.sleep(3600)

    def _collect_metrics_loop(self):
        """Collect metrics every 5 seconds (reduced from 1s for performance)"""
        while True:
            try:
                metrics = self.get_system_metrics()
                self.metrics_history.append(metrics)
                self.last_update = time.time()
                time.sleep(5)  # 5 second interval = 12 samples/minute
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
    
    # ---- System Metrics ----
    
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
            'network_rx_mbps': 0,  # Calculated over time
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
        
        # Sample to ~60 data points
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
        return round(bytes_total * 8 / 500_000, 1)  # Mbps over 0.5s
    
    def _get_uptime(self):
        """Get system uptime in human readable format"""
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    

        
    # ---- VM Management (Universal Detection with Aggressive Caching) ----

    def get_vms_list(self, force_refresh=False):
        """
        Universal VM detection with aggressive caching.
        Designed for low-resource devices (1GB RAM).
        Cache TTL: 60 seconds to minimize subprocess calls.
        """
        
        # Cache for 60 seconds (longer = less CPU usage)
        cache_ttl = 60  # seconds
        
        # Check if we have a valid cache
        if hasattr(self, '_vms_cache') and not force_refresh:
            cache_age = time.time() - getattr(self, '_vms_cache_time', 0)
            if cache_age < cache_ttl:
                return self._vms_cache  # Silent return - no logging spam
        
        vms = []
        seen_names = set()
        
        # Define known VMs
        known_vm_names = ['k8s-node-01', 'k8s-node-02', 'k8s-node-03']
        known_vm_ips = {
            'k8s-node-01': '10.0.0.21',
            'k8s-node-02': '10.0.0.22',
            'k8s-node-03': '10.0.0.23'
        }
        
        # ------------------------------------------------------------------
        # METHOD 1: libvirt / KVM / QEMU (virsh) - Quick check only
        # ------------------------------------------------------------------
        try:
            result = subprocess.run(['virsh', 'list', '--all'], 
                                capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[2:]
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 3:
                            vm_name = parts[1]
                            vm_state = parts[2]
                            if vm_name not in seen_names:
                                seen_names.add(vm_name)
                                vms.append({
                                    'name': vm_name,
                                    'state': vm_state,
                                    'ip': 'unknown',
                                    'hypervisor': 'libvirt',
                                    'id': parts[0] if parts[0] != '-' else None,
                                    'cpu': '0%',
                                    'ram': '0%',
                                    'disk': '0%'
                                })
        except Exception:
            pass  # Silently skip errors
        
        # ------------------------------------------------------------------
        # METHOD 2: QEMU Processes (only if no VMs found)
        # ------------------------------------------------------------------
        if len(vms) == 0:
            try:
                result = subprocess.run(
                    "ps aux 2>/dev/null | grep -E 'qemu-system|kvm' | grep -v grep | grep -oP '(?<=-name\\s)\\S+' | head -5",
                    shell=True, capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    for name in result.stdout.strip().split('\n'):
                        name = name.strip().rstrip(',')
                        if name in known_vm_names:
                            continue
                        if name and name not in seen_names:
                            seen_names.add(name)
                            vms.append({
                                'name': name,
                                'state': 'running',
                                'ip': 'unknown',
                                'hypervisor': 'qemu',
                                'id': None,
                                'cpu': '0%',
                                'ram': '0%',
                                'disk': '0%'
                            })
            except Exception:
                pass
        
        # ------------------------------------------------------------------
        # METHOD 3: Docker Containers (only if no VMs found)
        # ------------------------------------------------------------------
        if len(vms) == 0:
            try:
                result = subprocess.run(
                    "docker ps -a --format '{{.Names}}' 2>/dev/null | head -10",
                    shell=True, capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    for name in result.stdout.strip().split('\n'):
                        name = name.strip()
                        if name in known_vm_names:
                            continue
                        if any(kw in name.lower() for kw in ['node', 'vm', 'k3s', 'k8s', 'worker', 'master']):
                            if name not in seen_names:
                                seen_names.add(name)
                                vms.append({
                                    'name': name,
                                    'state': 'running',
                                    'ip': 'container',
                                    'hypervisor': 'docker',
                                    'id': None,
                                    'cpu': '0%',
                                    'ram': '0%',
                                    'disk': '0%'
                                })
            except Exception:
                pass
        
        # ------------------------------------------------------------------
        # METHOD 4: LXC / LXD Containers (only if no VMs found)
        # ------------------------------------------------------------------
        if len(vms) == 0:
            try:
                result = subprocess.run(
                    "lxc list --format csv -c n 2>/dev/null | head -10",
                    shell=True, capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    for name in result.stdout.strip().split('\n'):
                        name = name.strip()
                        if name in known_vm_names:
                            continue
                        if name and name not in seen_names:
                            seen_names.add(name)
                            vms.append({
                                'name': name,
                                'state': 'running',
                                'ip': 'lxc',
                                'hypervisor': 'lxc',
                                'id': None,
                                'cpu': '0%',
                                'ram': '0%',
                                'disk': '0%'
                            })
            except Exception:
                pass
        
        # ------------------------------------------------------------------
        # METHOD 5: Known VMs (ALWAYS included)
        # ------------------------------------------------------------------
        for ip, name in known_vm_ips.items():
            if name not in seen_names:
                seen_names.add(name)
                # Quick ping with 1 second timeout
                reachable = False
                try:
                    result = subprocess.run(
                        f"ping -c 1 -W 1 {ip} >/dev/null 2>&1",
                        shell=True, timeout=1
                    )
                    reachable = result.returncode == 0
                except:
                    pass
                
                vms.append({
                    'name': name,
                    'state': 'running' if reachable else 'offline',
                    'ip': ip,
                    'hypervisor': 'known',
                    'id': None,
                    'cpu': '0%',
                    'ram': '0%',
                    'disk': '0%'
                })
        
        # Cache the results
        self._vms_cache = vms
        self._vms_cache_time = time.time()
        
        # Single log line with method count (not every time)
        if not hasattr(self, '_vms_log_count'):
            self._vms_log_count = 0
        
        self._vms_log_count += 1
        if self._vms_log_count % 5 == 1:  # Log every 5th cache refresh
            print(f"VM detection: {len(vms)} VMs cached ({cache_ttl}s TTL)")
        
        return vms
    
    def _get_vm_ip(self, vm_name):
        """Get IP address - multiple methods"""
        # virsh with agent
        try:
            result = subprocess.run(['virsh', 'domifaddr', vm_name, '--source', 'agent'], 
                                  capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if 'ipv4' in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[-1].split('/')[0]
                        if ip and ip != '0.0.0.0':
                            return ip
        except:
            pass
        # virsh without agent
        try:
            result = subprocess.run(['virsh', 'domifaddr', vm_name], 
                                  capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if 'ipv4' in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[-1].split('/')[0]
                        if ip and ip != '0.0.0.0':
                            return ip
        except:
            pass
        # Known IPs
        known_ips = {
            'k8s-node-01': '10.0.0.21',
            'k8s-node-02': '10.0.0.22',
            'k8s-node-03': '10.0.0.23',
        }
        if vm_name in known_ips:
            ip = known_ips[vm_name]
            try:
                result = subprocess.run(
                    f"ping -c 1 -W 1 {ip} 2>/dev/null",
                    shell=True, capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    return ip
            except:
                pass
        return 'unknown'
    
    def _get_vm_cpu(self, vm_name):
        try:
            result = subprocess.run(
                f"virsh domstats {vm_name} --cpu-total 2>/dev/null | grep 'cpu.time' | cut -d= -f2",
                shell=True, capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                cpu_ns = int(result.stdout.strip())
                return f"{min(cpu_ns / 1000000000, 100):.0f}%"
        except:
            pass
        return '0%'
    
    def _get_vm_ram(self, vm_name):
        try:
            result = subprocess.run(
                f"virsh domstats {vm_name} --balloon 2>/dev/null | grep 'balloon.current' | cut -d= -f2",
                shell=True, capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                mem_kb = int(result.stdout.strip())
                mem_gb = mem_kb / (1024 * 1024)
                return f"{mem_gb:.1f}Gi" if mem_gb >= 1 else f"{mem_kb/1024:.0f}Mi"
            result = subprocess.run(
                f"virsh dominfo {vm_name} 2>/dev/null | grep 'Used memory' | awk '{{print $3, $4}}'",
                shell=True, capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass
        return '0Mi'
    
    def _get_vm_disk(self, vm_name):
        try:
            result = subprocess.run(
                f"virsh domblklist {vm_name} --details 2>/dev/null | grep -E 'vda|sda|hda' | awk '{{print $4}}' | head -1",
                shell=True, capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                disk_path = result.stdout.strip()
                result2 = subprocess.run(
                    f"qemu-img info '{disk_path}' 2>/dev/null | grep 'virtual size' | awk '{{print $3, $4}}'",
                    shell=True, capture_output=True, text=True, timeout=3
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    return result2.stdout.strip()
                return disk_path
        except:
            pass
        return '0GiB'
    
    def get_vm_details(self, vm_name):
        """Get comprehensive VM details"""
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
            result = subprocess.run(
                f'virsh domstats {vm_name} --cpu-total',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        details['cpu_stats'][key.strip()] = value.strip()
            result = subprocess.run(
                f'virsh snapshot-list {vm_name} --name',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                details['snapshots'] = [s.strip() for s in result.stdout.split('\n') if s.strip()]
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
        except Exception as e:
            details['error'] = str(e)
        return details
    
    # ---- Kubernetes Management ----
    
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
    
    # ---- Event Management ----
    
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
            self.alerts.append({
                **event,
                'acknowledged': False,
                'resolved': False
            })
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
    
    # ---- Actions (FULLY UPGRADED) ----
    
    def execute_action(self, resource_type, resource_name, action, params=None):
        """Execute an action with optional parameters (e.g., replicas for scale)"""
        if params is None:
            params = {}
        job_id = hashlib.md5(f"{time.time()}{resource_name}{action}".encode()).hexdigest()[:12]
        
        # Build command with parameter substitution
        def substitute(cmd):
            for key, value in params.items():
                cmd = cmd.replace(f"{{{key}}}", str(value))
            return cmd
        
        action_map = {
            # ---- VM actions ----
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
            
            # ---- Kubernetes Pod actions ----
            'pod_restart': [
                {'name': 'Delete pod', 'type': 'command', 'command': f'kubectl delete pod {resource_name}'},
                {'name': 'Wait for restart', 'type': 'sleep', 'duration': 10},
                {'name': 'Verify running', 'type': 'verify', 'command': f'kubectl get pod {resource_name} -o jsonpath="{{.status.phase}}" | grep Running'}
            ],
            'pod_delete': [
                {'name': 'Delete pod', 'type': 'command', 'command': f'kubectl delete pod {resource_name}'},
                {'name': 'Wait', 'type': 'sleep', 'duration': 5}
            ],
            
            # ---- Kubernetes Deployment actions ----
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
            
            # ---- Kubernetes Node actions ----
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
# WEBSOCKET SERVER
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
                params  # pass full params dict for extra args
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
        
        # Parse query parameters for GET-style POST requests
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        
        routes = {
            '/api/diagnostics': lambda: self.api_run_diagnostics(),
            '/api/repair': lambda: self.api_run_repair(params.get('target')),
            '/api/execute': lambda: self.api_execute_action(params),
            '/api/alerts/acknowledge': lambda: self.api_acknowledge_alert(params),
            '/api/terminal': lambda: self.api_terminal(params),  # ← TERMINAL ENDPOINT
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
        return {
            'status': 'connected',
            'hosts_online': 1,
            'vms_running': len([v for v in self.monitor.get_vms_list() if v['state'] == 'running']),
            'k8s_available': self.monitor.get_kubernetes_resources()['available'],
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
    
    def api_run_diagnostics(self):
        return self.monitor.run_diagnostics()
    
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
    
    # ---- TERMINAL API ----
    def api_terminal(self, params):
        """Execute a terminal command and return output"""
        command = params.get('command', '')
        if not command:
            return {'error': 'No command provided'}
        
        # Whitelist of safe commands
        safe_commands = [
            'ping', 'kubectl', 'virsh', 'docker', 'systemctl', 
            'ps', 'top', 'df', 'free', 'netstat', 'ss', 'ip', 
            'ifconfig', 'route', 'nslookup', 'dig', 'curl', 'hostname',
            'whoami', 'date', 'uptime', 'uname', 'cat', 'echo',
            'k3s', 'kubectl', 'helm'
        ]
        
        # Check if command is safe
        cmd_parts = command.split()
        if cmd_parts and cmd_parts[0] not in safe_commands:
            return {'error': f'Command "{cmd_parts[0]}" is not allowed. Allowed: {", ".join(safe_commands)}'}
        
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=30
            )
            output = result.stdout + result.stderr
            return {
                'output': output,
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
        print("HTTP Server stopped")

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
            print("WebSocket Server stopped")

def main():
    print("=" * 60)
    print("  Infrastructure Operations Center v3.1.0")
    print("  Full WebSocket & REST API")
    print("=" * 60)
    print()
    monitor = InfrastructureMonitor()
    monitor.add_event('system', 'Infrastructure Operations Center started', 'info')
    print(f"  📊 Metrics collection: Active (1s interval)")
    print(f"  🤖 Automation engine: Ready")
    print(f"  📝 Event stream: Active")
    print(f"  📋 Job queue: Ready")
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