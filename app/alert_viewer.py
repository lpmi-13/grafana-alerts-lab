#!/usr/bin/env python3
"""In-playground Grafana webhook receiver and incident display."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PAGE = Path(__file__).with_name("viewer.html").read_bytes()
CHECKOUT_URL = os.environ.get("CHECKOUT_URL", "http://127.0.0.1:9103")
EVENTS = []
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, body, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.respond(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/healthz":
            self.respond(200, b'{"status":"ok"}')
        elif self.path == "/api/events":
            with LOCK:
                body = json.dumps(EVENTS[-30:]).encode()
            self.respond(200, body)
        else:
            self.respond(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path in ("/api/fault/on", "/api/fault/off"):
            action = self.path.rsplit("/", 1)[-1]
            request = urllib.request.Request(f"{CHECKOUT_URL}/fault/{action}", data=b"", method="POST")
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.respond(200, response.read())
            except (urllib.error.URLError, TimeoutError) as error:
                self.respond(502, json.dumps({"error": str(error)}).encode())
            return

        if self.path != "/webhook":
            self.respond(404, b'{"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid payload length")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
            alerts = payload.get("alerts", [])
            labels = alerts[0].get("labels", {}) if alerts else {}
            event = {
                "id": time.time_ns(),
                "time": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "status": payload.get("status", "unknown"),
                "title": payload.get("title") or payload.get("commonLabels", {}).get("alertname") or "Grafana alert",
                "service": labels.get("service") or payload.get("commonLabels", {}).get("service") or "checkout",
                "message": payload.get("message") or "Grafana sent a webhook notification.",
            }
            with LOCK:
                EVENTS.append(event)
                del EVENTS[:-100]
            self.respond(200, b'{"received":true}')
        except (ValueError, json.JSONDecodeError) as error:
            self.respond(400, json.dumps({"error": str(error)}).encode())


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
