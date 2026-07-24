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
        self.metrics_history = deque(maxlen=3600)  # 1 hour of 1-second data
        self.events = deque(maxlen=1000)
        self.alerts = []
        self.audit_log = deque(maxlen=10000)
        self.timeline = deque(maxlen=500)
        self.last_update = time.time()
        
        # Initialize default automations
        self._init_automations()
        
        # Start background tasks
        threading.Thread(target=self._collect_metrics_loop, daemon=True).start()
        threading.Thread(target=self._process_jobs_loop, daemon=True).start()
    
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
    
    def _collect_metrics_loop(self):
        """Continuously collect metrics every second"""
        while True:
            try:
                metrics = self.get_system_metrics()
                self.metrics_history.append(metrics)
                self.last_update = time.time()
                time.sleep(1)
            except:
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
    
    # ---- VM Management ----
    
    def get_vms_list(self):
        """Get list of all VMs via virsh"""
        try:
            result = subprocess.run(['virsh', 'list', '--all'], 
                                  capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split('\n')[2:]  # Skip header
            vms = []
            for line in lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 3:
                        vm_name = parts[1]
                        vms.append({
                            'id': parts[0] if parts[0] != '-' else None,
                            'name': vm_name,
                            'state': parts[2],
                            'ip': self._get_vm_ip(vm_name),
                            'cpu': '0%',
                            'ram': '0%',
                            'disk': '0%'
                        })
            return vms
        except:
            return []
    
    def _get_vm_ip(self, vm_name):
        """Get IP address of a VM"""
        try:
            result = subprocess.run(['virsh', 'domifaddr', vm_name], 
                                  capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if 'ipv4' in line.lower():
                    return line.split()[-1].split('/')[0]
        except:
            pass
        return 'unknown'
    
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
            # Domain info
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
            
            # CPU stats
            result = subprocess.run(
                f'virsh domstats {vm_name} --cpu-total',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        details['cpu_stats'][key.strip()] = value.strip()
            
            # Snapshots
            result = subprocess.run(
                f'virsh snapshot-list {vm_name} --name',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                details['snapshots'] = [s.strip() for s in result.stdout.split('\n') if s.strip()]
            
            # Disk info
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
            
            # Network interfaces
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
        """Get comprehensive Kubernetes resources"""
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
            # Check if kubectl is available
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
                        'age': self._calculate_age(item['metadata']['creationTimestamp']),
                        'labels': item['metadata'].get('labels', {})
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
        """Determine node readiness status"""
        for condition in node['status'].get('conditions', []):
            if condition['type'] == 'Ready':
                return 'Ready' if condition['status'] == 'True' else 'NotReady'
        return 'Unknown'
    
    def _calculate_age(self, timestamp):
        """Calculate human-readable age from timestamp"""
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
        """Add an event to the stream and timeline"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'message': message,
            'severity': severity,
            'id': hashlib.md5(f"{time.time()}{message}".encode()).hexdigest()[:8]
        }
        self.events.appendleft(event)
        self.timeline.append(event)
        
        # Auto-create alerts for critical events
        if severity in ('critical', 'error'):
            self.alerts.append({
                **event,
                'acknowledged': False,
                'resolved': False
            })
        
        return event
    
    def add_audit(self, user, action, resource):
        """Add an audit log entry"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'user': user,
            'action': action,
            'resource': resource
        }
        self.audit_log.appendleft(entry)
        return entry
    
    def get_timeline(self, hours=1):
        """Get event timeline for correlation view"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [e for e in self.timeline if datetime.fromisoformat(e['timestamp']) > cutoff]
    
    # ---- Actions ----
    
    def execute_action(self, resource_type, resource_name, action):
        """Execute an action on a resource with job tracking"""
        job_id = hashlib.md5(f"{time.time()}{resource_name}{action}".encode()).hexdigest()[:12]
        
        # Define action workflows
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
            'pod_restart': [
                {'name': 'Delete pod', 'type': 'command', 'command': f'kubectl delete pod {resource_name}'},
                {'name': 'Wait for restart', 'type': 'sleep', 'duration': 10},
                {'name': 'Verify running', 'type': 'verify', 'command': f'kubectl get pod {resource_name} -o jsonpath="{{.status.phase}}" | grep Running'}
            ],
            'node_drain': [
                {'name': 'Cordon node', 'type': 'command', 'command': f'kubectl cordon {resource_name}'},
                {'name': 'Drain node', 'type': 'command', 'command': f'kubectl drain {resource_name} --ignore-daemonsets --delete-emptydir-data --force'},
                {'name': 'Verify', 'type': 'verify', 'command': f'kubectl get node {resource_name} -o jsonpath="{{.spec.unschedulable}}" | grep true'}
            ],
            'node_uncordon': [
                {'name': 'Uncordon node', 'type': 'command', 'command': f'kubectl uncordon {resource_name}'}
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
        """Run full network diagnostics using existing tool"""
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
        """Run network repair using existing tool"""
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
        """Run diagnostics and return structured problems"""
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
        """Search across all infrastructure resources"""
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
        
        return results[:20]  # Limit to 20 results


# ============================================================
# WEBSOCKET SERVER
# ============================================================

class WebSocketServer:
    """WebSocket server for real-time bidirectional communication"""
    
    def __init__(self, monitor):
        self.monitor = monitor
        self.clients = set()
        self.subscriptions = {}  # client_id -> [topics]
    
    async def handler(self, websocket, path):
        """Handle individual WebSocket connections"""
        self.clients.add(websocket)
        client_id = id(websocket)
        self.subscriptions[client_id] = ['metrics', 'events']
        
        try:
            # Send welcome message
            await websocket.send(json.dumps({
                'type': 'connected',
                'data': {
                    'client_id': client_id,
                    'timestamp': datetime.now().isoformat()
                }
            }))
            
            # Handle incoming messages
            async for message in websocket:
                try:
                    data = json.loads(message)
                    response = await self.handle_command(data, client_id)
                    await websocket.send(json.dumps(response))
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Invalid JSON'
                    }))
                except Exception as e:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': str(e)
                    }))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            if client_id in self.subscriptions:
                del self.subscriptions[client_id]
    
    async def handle_command(self, data, client_id):
        """Route commands to appropriate handlers"""
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
                params.get('action', '')
            ),
            'get_job_status': lambda: self.monitor.automation.get_job_status(params.get('job_id', '')),
            'subscribe': lambda: self._handle_subscribe(client_id, params.get('topics', [])),
            'unsubscribe': lambda: self._handle_unsubscribe(client_id, params.get('topics', [])),
            'acknowledge_alert': lambda: self._acknowledge_alert(params.get('alert_id', '')),
        }
        
        if command in handlers:
            try:
                result = handlers[command]()
                return {
                    'type': f'{command}_response',
                    'data': result,
                    'request_id': request_id
                }
            except Exception as e:
                return {
                    'type': 'error',
                    'message': str(e),
                    'request_id': request_id
                }
        
        return {
            'type': 'error',
            'message': f'Unknown command: {command}',
            'request_id': request_id
        }
    
    def _handle_subscribe(self, client_id, topics):
        """Subscribe client to specific topics"""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].extend(topics)
            self.subscriptions[client_id] = list(set(self.subscriptions[client_id]))
        return {'subscribed': topics}
    
    def _handle_unsubscribe(self, client_id, topics):
        """Unsubscribe client from specific topics"""
        if client_id in self.subscriptions:
            self.subscriptions[client_id] = [
                t for t in self.subscriptions[client_id] if t not in topics
            ]
        return {'unsubscribed': topics}
    
    def _acknowledge_alert(self, alert_id):
        """Mark an alert as acknowledged"""
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
        """Periodically broadcast updates to all connected clients"""
        while True:
            try:
                # Broadcast metrics every second
                metrics = self.monitor.get_system_metrics()
                await self.broadcast({
                    'type': 'metrics_update',
                    'data': metrics
                }, topic='metrics')
                
                # Broadcast recent events
                recent_events = list(self.monitor.events)[:20]
                if recent_events:
                    await self.broadcast({
                        'type': 'events_update',
                        'data': recent_events
                    }, topic='events')
                
                # Broadcast alerts
                active_alerts = [a for a in self.monitor.alerts if not a.get('resolved')]
                if active_alerts:
                    await self.broadcast({
                        'type': 'alerts_update',
                        'data': active_alerts
                    }, topic='alerts')
                
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Broadcast error: {e}")
                await asyncio.sleep(5)


# ============================================================
# HTTP API SERVER
# ============================================================

class APIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with REST API endpoints"""
    
    # Use class variable for monitor (set before starting server)
    monitor = None
    
    def __init__(self, *args, **kwargs):
        # Serve from static directory
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path.startswith('/api/'):
            self.handle_api_get()
        else:
            # Serve static files
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
        """Route GET API requests"""
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
        """Route POST API requests"""
        path = self.path.split('?')[0]
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        try:
            params = json.loads(body)
        except:
            params = {}
        
        # Parse query parameters
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(self.path).query)
        
        routes = {
            '/api/diagnostics': lambda: self.api_run_diagnostics(),
            '/api/repair': lambda: self.api_run_repair(params.get('target')),
            '/api/execute': lambda: self.api_execute_action(params),
            '/api/alerts/acknowledge': lambda: self.api_acknowledge_alert(params),
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
        """Handle CORS preflight"""
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
            params.get('action', '')
        )
    
    def api_acknowledge_alert(self, params):
        alert_id = params.get('alert_id', '')
        for alert in self.monitor.alerts:
            if alert.get('id') == alert_id:
                alert['acknowledged'] = True
                return {'acknowledged': True}
        return {'acknowledged': False, 'error': 'Alert not found'}


# ============================================================
# SERVER STARTUP
# ============================================================

def start_http_server(monitor):
    """Start the HTTP server"""
    # Set monitor on the handler class
    APIHandler.monitor = monitor
    
    # Create static directory if it doesn't exist
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
    """Start the WebSocket server"""
    ws_server = WebSocketServer(monitor)
    
    print(f"🔌 WebSocket Server running on ws://localhost:{WS_PORT}")
    
    async with websockets.serve(ws_server.handler, HOST, WS_PORT):
        # Start broadcasting task
        broadcast_task = asyncio.create_task(ws_server.start_broadcasting())
        
        try:
            await asyncio.Future()  # Run forever
        except KeyboardInterrupt:
            pass
        finally:
            broadcast_task.cancel()
            print("WebSocket Server stopped")


def main():
    """Main entry point"""
    print("=" * 60)
    print("  Infrastructure Operations Center v3.0.0")
    print("  Three-Pane Operations Console")
    print("=" * 60)
    print()
    
    # Create monitor instance
    monitor = InfrastructureMonitor()
    monitor.add_event('system', 'Infrastructure Operations Center started', 'info')
    
    print(f"  📊 Metrics collection: Active (1s interval)")
    print(f"  🤖 Automation engine: Ready")
    print(f"  📝 Event stream: Active")
    print(f"  📋 Job queue: Ready")
    print()
    
    # Start HTTP server in a daemon thread
    http_thread = threading.Thread(
        target=start_http_server, 
        args=(monitor,), 
        daemon=True,
        name="HTTP-Server"
    )
    http_thread.start()
    
    # Run WebSocket server in main thread (asyncio)
    try:
        asyncio.run(start_ws_server(monitor))
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        raise


if __name__ == '__main__':
    main()