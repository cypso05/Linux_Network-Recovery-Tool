#!/usr/bin/env python3
"""Network Recovery Tool - Web Backend"""

import http.server
import json
import subprocess
import os
import sys
import argparse
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
NETWORK_RECOVER = "/usr/local/bin/network-recover"

class APIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        # API endpoints
        if path == "/api/status":
            self.json_response(self.run_cmd(["status"]))
        elif path == "/api/diagnose":
            self.json_response(self.run_cmd(["diagnose"]))
        elif path == "/api/repair":
            self.json_response(self.run_cmd(["repair"]))
        elif path == "/api/snapshot":
            self.json_response(self.run_cmd(["snapshot"]))
        else:
            # Serve static files
            super().do_GET()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/api/action":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                action = data.get('action', 'status')
                
                # Run the command
                result = self.run_cmd([action])
                self.json_response(result)
            except Exception as e:
                self.json_response({"ok": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()
    
    def run_cmd(self, args):
        try:
            # Use sudo with the full path
            cmd = ["sudo", NETWORK_RECOVER] + args
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            # Parse output for better formatting
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            
            return {
                "ok": result.returncode == 0,
                "output": output,
                "exit_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Command timed out"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    
    server = http.server.HTTPServer((args.host, args.port), APIHandler)
    print(f"🌐 Network Recovery Web UI: http://{args.host}:{args.port}")
    print(f"📋 Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()