#!/usr/bin/env python3
"""Network Recovery Tool - Self-Contained Web Backend"""

import http.server
import json
import subprocess
import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
NETWORK_RECOVER = "/usr/local/bin/network-recover"

class APIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)
    
    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == "/api/status":
            self.json_response(self.run_cmd(["status"]))
        elif path == "/api/diagnose":
            self.json_response(self.run_cmd(["diagnose"]))
        elif path == "/api/repair":
            self.json_response(self.run_cmd(["repair"]))
        elif path == "/api/snapshot":
            self.json_response(self.run_cmd(["snapshot"]))
        elif path == "/api/stream/diagnose":
            self.stream_cmd(["diagnose"])
        elif path == "/api/stream/repair":
            self.stream_cmd(["repair"])
        else:
            super().do_GET()
    
    def run_cmd(self, args):
        try:
            r = subprocess.run(["sudo", NETWORK_RECOVER] + args,
                capture_output=True, text=True, timeout=120)
            return {"ok": r.returncode == 0, "out": r.stdout, "err": r.stderr}
        except subprocess.TimeoutExpired:
            return {"ok": False, "err": "Timeout"}
        except Exception as e:
            return {"ok": False, "err": str(e)}
    
    def stream_cmd(self, args):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        
        p = subprocess.Popen(["sudo", NETWORK_RECOVER] + args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        layer_map = {
            "LAYER 1": (1, "Physical"), "LAYER 2": (2, "Link"),
            "LAYER 3": (3, "IP"), "LAYER 4": (4, "Routing"),
            "LAYER 5": (5, "Gateway"), "LAYER 6": (6, "Internet"),
            "LAYER 7": (7, "DNS"), "LAYER 8": (8, "HTTPS"),
            "LAYER 9": (9, "NetworkManager"), "LAYER 10": (10, "Virtualization"),
            "LAYER 11": (11, "Kubernetes")
        }
        
        for line in p.stdout:
            data = {"type": "log", "msg": line.strip()}
            if "?" in line: data["status"] = "pass"
            elif "?" in line: data["status"] = "fail"
            elif "??" in line: data["status"] = "warn"
            elif "??" in line: data["status"] = "info"
            
            for key, (num, name) in layer_map.items():
                if key in line:
                    data.update({"type": "layer", "layer": num, "name": name})
                    break
            
            self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
        
        p.wait()
        self.wfile.write(f'data: {{"type":"done","code":{p.returncode}}}\n\n'.encode())
        self.wfile.flush()
    
    def json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9876)
    args = parser.parse_args()
    
    server = http.server.HTTPServer(("127.0.0.1", args.port), APIHandler)
    print(f"Network Recovery Web UI: http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == "__main__":
    main()