#!/usr/bin/env python3
"""In-playground Grafana webhook receiver, incident display, and destination manager."""

import base64
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PAGE = Path(__file__).with_name("viewer.html").read_bytes()
CHECKOUT_URL = os.environ.get("CHECKOUT_URL", "http://127.0.0.1:9103")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://127.0.0.1:3000")
GRAFANA_AUTH = "Basic " + base64.b64encode(os.environ.get("GRAFANA_AUTH", "admin:lab-demo").encode()).decode()
EVENTS = []
LOCK = threading.Lock()

# Every lab alert goes to one contact point. The inbox webhook is always one of
# its integrations; the learner's webhook and PagerDuty service are optional extras.
CONTACT_POINT = "Lab alerts"
INBOX = {
    "uid": "lab_webhook",
    "name": CONTACT_POINT,
    "type": "webhook",
    "settings": {"url": "http://127.0.0.1:8081/webhook", "httpMethod": "POST"},
}
POLICY = {
    "receiver": CONTACT_POINT,
    "group_by": ["grafana_folder", "alertname"],
    "group_wait": "0s",
    "group_interval": "1m",
    "repeat_interval": "1h",
}
DESTINATIONS = {"webhook": "byo_webhook", "pagerduty": "byo_pagerduty"}
DISCORD_HOSTS = {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
LABELS = {"discord": "Discord webhook", "slack": "Slack webhook", "pagerduty": "PagerDuty Events API"}
ROUTING_READY = threading.Event()
ROUTING_LOCK = threading.Lock()


def grafana(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Authorization": GRAFANA_AUTH, "Content-Type": "application/json"}
    if method in ("POST", "PUT"):
        # Let learners edit API-created contact points and policies in Grafana.
        headers["X-Disable-Provenance"] = "true"
    request = urllib.request.Request(
        f"{GRAFANA_URL}/api/v1/provisioning{path}", data=data, method=method,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read() or b"null")


def grafana_error(error):
    if isinstance(error, urllib.error.HTTPError):
        try:
            return f"Grafana returned {error.code}: {json.loads(error.read())['message']}"
        except (ValueError, KeyError, TypeError):
            return f"Grafana returned {error.code}"
    return f"Grafana is unreachable: {error}"


def integrations():
    return grafana("GET", "/contact-points?name=" + urllib.parse.quote(CONTACT_POINT))


def ensure_routing():
    if not any(item["uid"] == INBOX["uid"] for item in integrations()):
        grafana("POST", "/contact-points", INBOX)
    policy = grafana("GET", "/policies")
    # Initialize Grafana's default route once. Keep later UI changes, including
    # child policies, when the inbox service restarts.
    if policy.get("receiver") in ("empty", "grafana-default-email") and not policy.get("routes"):
        grafana("PUT", "/policies", POLICY)


def wait_for_grafana():
    while True:
        try:
            with ROUTING_LOCK:
                ensure_routing()
            ROUTING_READY.set()
            return
        except (OSError, ValueError) as error:
            if isinstance(error, urllib.error.HTTPError):
                print(grafana_error(error), file=sys.stderr, flush=True)
            time.sleep(2)


def describe(integration):
    if integration["type"] == "webhook":
        host = urllib.parse.urlsplit(integration["settings"].get("url", "")).hostname
        return f"Webhook to {host or 'an unknown host'}"
    return LABELS.get(integration["type"], integration["type"])


def destinations():
    configured = {item["uid"]: describe(item) for item in integrations()}
    return {kind: configured.get(uid) for kind, uid in DESTINATIONS.items()}


def webhook_integration(url):
    """Pick the Grafana integration that can talk to the URL's service."""
    url = url.strip() if isinstance(url, str) else ""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(url) > 2000:
        raise ValueError("Enter an http or https URL.")
    host = parts.hostname.lower()
    if host in DISCORD_HOSTS and parts.path.startswith("/api/webhooks/"):
        return "discord", {"url": url}
    if host == "hooks.slack.com":
        return "slack", {"url": url}
    if host == "ntfy.sh" and not {"template", "tpl"} & urllib.parse.parse_qs(parts.query).keys():
        query = urllib.parse.urlencode(urllib.parse.parse_qsl(parts.query) + [("template", "grafana")])
        url = urllib.parse.urlunsplit(parts._replace(query=query))
    return "webhook", {"url": url, "httpMethod": "POST"}


def pagerduty_integration(key):
    key = key.strip() if isinstance(key, str) else ""
    if not re.fullmatch(r"[A-Za-z0-9]{32}", key):
        raise ValueError("A PagerDuty Events API v2 integration key is 32 letters and digits.")
    return "pagerduty", {"integrationKey": key}


def save_destination(kind, payload):
    if kind == "webhook":
        integration_type, settings = webhook_integration(payload.get("url"))
    else:
        integration_type, settings = pagerduty_integration(payload.get("key"))
    integration = {"uid": DESTINATIONS[kind], "name": CONTACT_POINT, "type": integration_type, "settings": settings}
    try:
        grafana("PUT", f"/contact-points/{integration['uid']}", integration)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        grafana("POST", "/contact-points", integration)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, body, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("invalid payload length")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        return payload

    def manage_destinations(self, method):
        kind = self.path.removeprefix("/api/destinations/")
        if method != "GET" and kind not in DESTINATIONS:
            self.respond(404, b'{"error":"not found"}')
            return
        if not ROUTING_READY.is_set():
            self.respond(503, b'{"error":"Grafana is still starting. Try again shortly."}')
            return
        try:
            with ROUTING_LOCK:
                if method == "POST":
                    save_destination(kind, self.read_json())
                elif method == "DELETE":
                    grafana("DELETE", f"/contact-points/{DESTINATIONS[kind]}")
                code, body = 200, destinations()
        except ValueError as error:
            code, body = 400, {"error": str(error)}
        except OSError as error:
            code, body = 502, {"error": grafana_error(error)}
        self.respond(code, json.dumps(body).encode())

    def do_GET(self):
        if self.path == "/":
            self.respond(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/healthz":
            self.respond(200, b'{"status":"ok"}')
        elif self.path == "/api/events":
            with LOCK:
                body = json.dumps(EVENTS[-30:]).encode()
            self.respond(200, body)
        elif self.path == "/api/destinations":
            self.manage_destinations("GET")
        else:
            self.respond(404, b'{"error":"not found"}')

    def do_DELETE(self):
        self.manage_destinations("DELETE")

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

        if self.path.startswith("/api/destinations/"):
            self.manage_destinations("POST")
            return

        if self.path != "/webhook":
            self.respond(404, b'{"error":"not found"}')
            return
        try:
            payload = self.read_json()
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
    threading.Thread(target=wait_for_grafana, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
