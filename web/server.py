#!/usr/bin/env python3
"""Network Recovery Tool - Web Backend (Async, Thread-Safe, Low-Memory)"""

import http.server
import json
import subprocess
import os
import sys
import argparse
import threading
import time
import logging
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

# Configuration
WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
NETWORK_RECOVER = "/usr/local/bin/network-recover"
DASHBOARD_CMD = "/usr/local/bin/network-recover-dashboard"

# Limit threads on low-end devices (1-2GB RAM)
MAX_WORKERS = int(os.environ.get("NRT_WORKERS", "2"))
CMD_TIMEOUT = int(os.environ.get("NRT_CMD_TIMEOUT", "60"))
DASHBOARD_TIMEOUT = int(os.environ.get("NRT_DASHBOARD_TIMEOUT", "30"))

# Thread pool shared across all requests
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Cache for dashboard data (avoid hammering SSH on refreshes)
_dashboard_cache = {"data": None, "timestamp": 0, "ttl": 30}
_cache_lock = threading.Lock()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("nrt-web")


class APIHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that delegates work to a thread pool."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    # ------------------------------------------------------------------
    # Routing - GET
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            self.submit_async(["status"])
        elif path == "/api/diagnose":
            self.submit_async(["diagnose"])
        elif path == "/api/repair":
            self.submit_async(["repair"])
        elif path == "/api/snapshot":
            self.submit_async(["snapshot"])
        elif path == "/api/dashboard":
            self.submit_dashboard()
        elif path == "/api/dashboard/refresh":
            self.submit_dashboard(force_refresh=True)
        elif path == "/api/health":
            self.health_check()
        else:
            super().do_GET()

    # ------------------------------------------------------------------
    # Routing - POST
    # ------------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/action":
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 1024:
                self.json_response({"ok": False, "error": "Payload too large"})
                return
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                action = data.get('action', 'status')
                if action == 'dashboard':
                    self.submit_dashboard(force_refresh=True)
                else:
                    self.submit_async([action])
            except json.JSONDecodeError:
                self.json_response({"ok": False, "error": "Invalid JSON"})
            except Exception as e:
                self.json_response({"ok": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    # ------------------------------------------------------------------
    # Async submission helpers
    # ------------------------------------------------------------------
    def submit_async(self, args):
        """Run a command in the thread pool and respond when done."""
        future = executor.submit(self._run_cmd_sync, args)
        try:
            result = future.result(timeout=CMD_TIMEOUT + 5)
            self.json_response(result)
        except FutureTimeoutError:
            self.json_response({"ok": False, "error": "Request timed out"})

    def submit_dashboard(self, force_refresh=False):
        """Fetch dashboard data, using cache when possible."""
        if not force_refresh:
            with _cache_lock:
                if (_dashboard_cache["data"] is not None and
                        time.time() - _dashboard_cache["timestamp"] < _dashboard_cache["ttl"]):
                    logger.debug("Dashboard served from cache")
                    self.json_response(_dashboard_cache["data"])
                    return

        future = executor.submit(self._run_dashboard_sync)
        try:
            result = future.result(timeout=DASHBOARD_TIMEOUT + 5)
            with _cache_lock:
                _dashboard_cache["data"] = result
                _dashboard_cache["timestamp"] = time.time()
            self.json_response(result)
        except FutureTimeoutError:
            self.json_response({"ok": False, "error": "Dashboard request timed out"})

    def health_check(self):
        """Lightweight health endpoint."""
        pending = executor._work_queue.qsize() if hasattr(executor, '_work_queue') else 0
        self.json_response({
            "ok": True,
            "workers": MAX_WORKERS,
            "pending": pending,
            "cache_age": int(time.time() - _dashboard_cache["timestamp"]) if _dashboard_cache["data"] else 0,
            "cache_ttl": _dashboard_cache["ttl"]
        })

    # ------------------------------------------------------------------
    # Synchronous work (runs in thread pool)
    # ------------------------------------------------------------------
    @staticmethod
    def _run_cmd_sync(args):
        try:
            cmd = ["sudo", NETWORK_RECOVER] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return {
                "ok": result.returncode == 0,
                "output": output,
                "exit_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Command timed out after " + str(CMD_TIMEOUT) + "s"}
        except Exception as e:
            logger.error("run_cmd failed: %s", e)
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _run_dashboard_sync():
        if not os.path.exists(DASHBOARD_CMD):
            return {
                "ok": False,
                "error": "Dashboard script not installed. Run: sudo cp src/network-recover-dashboard " + DASHBOARD_CMD
            }
        try:
            result = subprocess.run(
                ["sudo", DASHBOARD_CMD, "json"],
                capture_output=True,
                text=True,
                timeout=DASHBOARD_TIMEOUT
            )
            if result.returncode != 0:
                return {
                    "ok": False,
                    "error": "Dashboard command failed",
                    "output": result.stderr
                }
            try:
                data = json.loads(result.stdout)
                data["ok"] = True
                return data
            except json.JSONDecodeError:
                return {
                    "ok": False,
                    "error": "Invalid JSON from dashboard",
                    "raw_output": result.stdout[:500]
                }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Dashboard timed out after " + str(DASHBOARD_TIMEOUT) + "s"}
        except Exception as e:
            logger.error("Dashboard failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------
    def json_response(self, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.info("%s - %s", self.client_address[0], format % args)


def main():
    parser = argparse.ArgumentParser(description="Network Recovery Tool - Web Server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NRT_PORT", "9876")))
    parser.add_argument("--host", type=str, default=os.environ.get("NRT_HOST", "0.0.0.0"))
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help="Thread pool size (default: 2, ideal for 1-2GB RAM)")
    args = parser.parse_args()

    global MAX_WORKERS
    MAX_WORKERS = args.workers

    # Recreate executor with configured worker count
    global executor
    executor.shutdown(wait=False)
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    server = http.server.HTTPServer((args.host, args.port), APIHandler)

    logger.info("Network Recovery Web UI: http://%s:%s", args.host, args.port)
    logger.info("Workers: %d | Cmd timeout: %ds | Dashboard timeout: %ds",
                MAX_WORKERS, CMD_TIMEOUT, DASHBOARD_TIMEOUT)
    logger.info("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        executor.shutdown(wait=True, timeout=5)
        server.shutdown()


if __name__ == "__main__":
    main()