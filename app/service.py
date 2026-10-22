#!/usr/bin/env python3
"""Five tiny HTTP services with Prometheus metrics and an injectable fault."""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SERVICES = {
    "catalog": 9101,
    "cart": 9102,
    "checkout": 9103,
    "payments": 9104,
    "shipping": 9105,
}


class State:
    def __init__(self, name):
        self.name = name
        self.fault = False
        self.ok = 0
        self.errors = 0
        self.tick = 0
        self.lock = threading.Lock()

    def record(self):
        with self.lock:
            self.tick += 1
            failed = self.fault and self.tick % 4 != 0
            if failed:
                self.errors += 1
            else:
                self.ok += 1
            return failed

    def metrics(self):
        with self.lock:
            fault, ok, errors = self.fault, self.ok, self.errors
        return (
            "# HELP lab_service_requests_total Synthetic and user HTTP work requests.\n"
            "# TYPE lab_service_requests_total counter\n"
            f'lab_service_requests_total{{service="{self.name}",status="ok"}} {ok}\n'
            f'lab_service_requests_total{{service="{self.name}",status="error"}} {errors}\n'
            "# HELP lab_service_error_ratio Current simulated error fraction.\n"
            "# TYPE lab_service_error_ratio gauge\n"
            f'lab_service_error_ratio{{service="{self.name}"}} {0.75 if fault else 0}\n'
            "# HELP lab_service_fault_enabled Whether the lab fault is enabled.\n"
            "# TYPE lab_service_fault_enabled gauge\n"
            f'lab_service_fault_enabled{{service="{self.name}"}} {1 if fault else 0}\n'
        ).encode()


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/metrics":
                self.respond(200, state.metrics(), "text/plain; version=0.0.4")
            elif self.path == "/healthz":
                self.respond(200, b'{"status":"ok"}')
            elif self.path == "/work":
                failed = state.record()
                body = json.dumps({"service": state.name, "status": "error" if failed else "ok"}).encode()
                self.respond(503 if failed else 200, body)
            else:
                self.respond(404, b'{"error":"not found"}')

        def do_POST(self):
            if self.path not in ("/fault/on", "/fault/off"):
                self.respond(404, b'{"error":"not found"}')
                return
            with state.lock:
                state.fault = self.path.endswith("/on")
            self.respond(200, json.dumps({"service": state.name, "fault": state.fault}).encode())

    return Handler


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SERVICES:
        raise SystemExit("usage: service.py <catalog|cart|checkout|payments|shipping>")
    name = sys.argv[1]
    state = State(name)

    def generate_traffic():
        while True:
            state.record()
            time.sleep(1)

    threading.Thread(target=generate_traffic, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", SERVICES[name]), handler_for(state)).serve_forever()


if __name__ == "__main__":
    main()
