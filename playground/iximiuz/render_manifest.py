#!/usr/bin/env python3
"""Render a self-contained iximiuz manifest for two to five VMs."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ["catalog", "cart", "checkout", "payments", "shipping"]
PORTS = {name: 9101 + index for index, name in enumerate(SERVICES)}


def yaml_scalar(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def dump_yaml(value, indent=0):
    spaces = " " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}{key}:")
                lines.append(dump_yaml(item, indent + 2))
            elif isinstance(item, str) and "\n" in item:
                lines.append(f"{spaces}{key}: {'|' if item.endswith(chr(10)) else '|-'}")
                lines.extend(f"{spaces}  {line}" for line in item.splitlines())
            else:
                lines.append(f"{spaces}{key}: {yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}-")
                lines.append(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{spaces}- {yaml_scalar(item)}")
        return "\n".join(lines)
    raise TypeError(type(value))


def startup_file(path, content, machines=None, mode="644"):
    entry = {"path": path, "owner": "root", "mode": mode, "content": content}
    if machines:
        entry["machines"] = machines
    return entry


def source_file(source, destination, machines=None):
    return startup_file(destination, (ROOT / source).read_text(), machines)


def render(vm_count, name):
    if not 2 <= vm_count <= 5:
        raise ValueError("iximiuz flexbox supports this lab with 2 to 5 VMs")
    names = ["monitor-01"] + [f"apps-{i:02d}" for i in range(2, vm_count + 1)]
    placement = {service: index % vm_count for index, service in enumerate(SERVICES)}
    checkout_ip = f"172.16.0.{placement['checkout'] + 2}"
    machines = []
    tasks = {}
    files = [
        source_file("app/service.py", "/opt/grafana-alerts-lab/service.py"),
        startup_file(
            "/etc/systemd/system/lab-service@.service",
            """[Unit]
Description=Metrics lab service %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=laborant
ExecStart=/usr/bin/python3 /opt/grafana-alerts-lab/service.py %i
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
""",
        ),
        source_file("app/alert_viewer.py", "/opt/grafana-alerts-lab/alert_viewer.py", [names[0]]),
        source_file("app/viewer.html", "/opt/grafana-alerts-lab/viewer.html", [names[0]]),
        startup_file(
            "/etc/systemd/system/lab-alert-viewer.service",
            """[Unit]
Description=Metrics lab alert inbox
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=laborant
Environment=CHECKOUT_URL=http://%s:9103
ExecStart=/usr/bin/python3 /opt/grafana-alerts-lab/alert_viewer.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
""" % checkout_ip,
            [names[0]],
        ),
        source_file("grafana/provisioning/datasources/prometheus.yaml", "/opt/grafana-alerts-lab/grafana/provisioning/datasources/prometheus.yaml", [names[0]]),
        source_file("grafana/provisioning/dashboards/lab.yaml", "/opt/grafana-alerts-lab/grafana/provisioning/dashboards/lab.yaml", [names[0]]),
        source_file("grafana/provisioning/alerting/checkout.yaml", "/opt/grafana-alerts-lab/grafana/provisioning/alerting/checkout.yaml", [names[0]]),
        source_file("grafana/dashboards/lab.json", "/opt/grafana-alerts-lab/grafana/dashboards/lab.json", [names[0]]),
    ]
    prometheus = "global:\n  scrape_interval: 5s\nscrape_configs:\n  - job_name: lab-services\n    static_configs:\n"
    for service in SERVICES:
        ip = f"172.16.0.{placement[service] + 2}"
        prometheus += f"      - targets: ['{ip}:{PORTS[service]}']\n        labels:\n          service: {service}\n"
    files.append(startup_file("/opt/grafana-alerts-lab/prometheus.yml", prometheus, [names[0]]))

    for index, machine_name in enumerate(names):
        services_here = [service for service in SERVICES if placement[service] == index]
        machines.append({
            "name": machine_name,
            "users": [
                {"name": "root"},
                {"name": "laborant", "default": True, "welcome": (
                    "Grafana Alerts Lab. Open the Grafana and Alert inbox tabs. "
                    "Trigger a checkout fault in the inbox, watch the dashboard, then restore it.\n"
                    f"This VM runs: {', '.join(services_here)}.\n"
                )},
            ],
            "drives": [{"source": "docker" if index == 0 else "ubuntu-24-04", "mount": "/", "size": "12GiB" if index == 0 else "8GiB"}],
            "network": {"interfaces": [{"address": f"172.16.0.{index + 2}/24", "network": "local"}]},
            "resources": {"cpuCount": (2 if vm_count < 5 else 1) if index == 0 else 1, "ramSize": "3GiB" if index == 0 else "1GiB"},
        })
        setup = [
            "#!/bin/bash",
            "set -euo pipefail",
            "if ! command -v python3 >/dev/null || ! command -v curl >/dev/null; then",
            "  apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl",
            "fi",
            "systemctl daemon-reload",
        ]
        setup += [f"systemctl enable --now lab-service@{service}.service" for service in services_here]
        setup += [f"curl --retry 20 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:{PORTS[service]}/healthz >/dev/null" for service in services_here]
        if index == 0:
            setup += [
                "systemctl enable --now lab-alert-viewer.service",
                "curl --retry 20 --retry-delay 1 --retry-connrefused -fsS http://127.0.0.1:8081/healthz >/dev/null",
                "systemctl enable --now docker.service",
                "for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done",
                "docker info >/dev/null",
                "docker pull prom/prometheus:v3.2.1",
                "docker pull grafana/grafana:12.4.13",
                "docker run -d --name lab-prometheus --restart unless-stopped --network host -v /opt/grafana-alerts-lab/prometheus.yml:/etc/prometheus/prometheus.yml:ro prom/prometheus:v3.2.1 --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.retention.time=6h --web.listen-address=0.0.0.0:9090",
                "docker run -d --name lab-grafana --restart unless-stopped --network host -e GF_UNIFIED_ALERTING_ALERTMANAGER_CONFIG_POLL_INTERVAL=10s -e GF_SECURITY_ADMIN_USER=admin -e GF_SECURITY_ADMIN_PASSWORD=lab-demo -e GF_AUTH_ANONYMOUS_ENABLED=true -e GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer -e GF_SECURITY_ALLOW_EMBEDDING=true -e GF_USERS_ALLOW_SIGN_UP=false -e GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/etc/grafana/dashboards/lab.json -v /opt/grafana-alerts-lab/grafana/provisioning:/etc/grafana/provisioning:ro -v /opt/grafana-alerts-lab/grafana/dashboards:/etc/grafana/dashboards:ro grafana/grafana:12.4.13",
                "curl --retry 90 --retry-delay 2 --retry-connrefused -fsS http://127.0.0.1:9090/-/ready >/dev/null",
                "curl --retry 90 --retry-delay 2 --retry-connrefused -fsS http://127.0.0.1:3000/api/health >/dev/null",
                "curl --retry 30 --retry-delay 2 --retry-connrefused -fsS -u admin:lab-demo http://127.0.0.1:3000/api/v1/provisioning/alert-rules/checkout_error_ratio >/dev/null",
                "curl --retry 30 --retry-delay 2 -fsS http://127.0.0.1:8081/api/destinations >/dev/null",
            ]
        task_name = f"init_{machine_name.replace('-', '_')}"
        tasks[task_name] = {
            "machine": machine_name, "init": True, "user": "root", "timeout_seconds": 900,
            "run": "\n".join(setup) + "\n",
        }
        if index == 0 and vm_count > 1:
            tasks[task_name]["needs"] = [f"init_{name.replace('-', '_')}" for name in names[1:]]

    tabs = [
        {"id": "grafana", "kind": "http-port", "name": "Grafana", "machine": names[0], "number": 3000, "pane": "left", "access": "public"},
        {"id": "alert-inbox", "kind": "http-port", "name": "Alert inbox", "machine": names[0], "number": 8081, "pane": "right", "access": "public"},
        {"id": "prometheus", "kind": "http-port", "name": "Prometheus", "machine": names[0], "number": 9090, "pane": "left", "access": "public"},
    ]
    tabs.extend({"id": f"terminal-{name}", "kind": "terminal", "name": name, "machine": name} for name in names)

    return {
        "kind": "playground",
        "name": name,
        "base": "flexbox",
        "title": "Grafana Alerts Lab",
        "description": "Explore metrics from five services across multiple VMs, trigger a Grafana alert, and watch its webhook appear in the lab.",
        "categories": ["linux", "observability"],
        "markdown": """## Trigger the alert

1. Open **Grafana** on the left and **Alert inbox** on the right. The dashboard shows five services spread across the VMs.
2. Click **Trigger checkout fault** in Alert inbox. Checkout's error ratio rises to 75%, Grafana fires its provisioned alert, and a popup appears in the inbox.
3. Click **Restore checkout** to receive the resolved notification.

Grafana login for exploring the alert rule and contact point: `admin` / `lab-demo`.

## Create your own alert and webhook in Grafana

1. Sign in to the **Grafana** tab as `admin` / `lab-demo`. Open **Alerts & IRM → Alerting → Notification configuration → Contact points**, click **New contact point**, choose **Webhook**, enter your URL, and save.
2. Open **Alerts & IRM → Alert rules → New alert rule**. Query **Prometheus** with `lab_service_error_ratio{service="checkout"}` and set the condition to **is above 0.2**.
3. Choose the **Lab** folder and create a new evaluation group, such as `my-alerts`, with a 10 second interval. Set the pending period to **None** or `0s`.
4. Under notifications, choose **Select contact point** and select your new webhook contact point. Save the rule, then click **Trigger checkout fault** in Alert inbox to test it.

The supplied checkout rule is file-provisioned and read-only in Grafana. Your new rule can send directly to your webhook; it does not need a notification policy change. Both checkout rules may notify you for the same fault. The **Lab alerts** contact point and default policy are editable in the UI.

## Send the alert to your own destination

Grafana's **Lab alerts** contact point always notifies Alert inbox. Under **Your destinations** in Alert inbox, you can add one webhook URL and one PagerDuty integration key, and Grafana notifies them too. Grafana picks up a saved destination within about 10 seconds.

Add your destination before you click **Trigger checkout fault**. An alert that is already firing is not resent to a replacement webhook URL until it resolves.

### Your phone, with ntfy

1. Install the [ntfy app](https://docs.ntfy.sh/subscribe/phone/) and subscribe to a hard to guess topic name, such as `grafana-lab-7f3k9q`. Anyone who knows the topic name can read its messages.
2. Paste `https://ntfy.sh/<your-topic>` into **Webhook URL** and click **Save webhook**. Alert inbox adds ntfy's `template=grafana` option, so the push notification reads as an alert instead of raw JSON.

### Discord

1. In a Discord server where you can manage webhooks, open the channel's **Edit Channel → Integrations → Webhooks**, create a webhook, and click **Copy Webhook URL**.
2. Paste it into **Webhook URL** and click **Save webhook**. Grafana sends it through its Discord integration.

Slack incoming webhook URLs (`https://hooks.slack.com/...`) work the same way. Any other URL, such as one from webhook.site, receives Grafana's webhook JSON unchanged.

### PagerDuty

1. On a PagerDuty service, add an **Events API v2** integration and copy its 32 character **Integration Key**.
2. Paste it into **PagerDuty integration key** and click **Save PagerDuty key**. A firing alert opens an incident and the resolved notification closes it.

Click **Remove** to stop sending to a destination. Destinations last for this session only. Grafana masks Discord, Slack, and PagerDuty secrets, but anyone who can open this session's Grafana can read a plain webhook URL such as an ntfy topic. Links inside the notifications point to Grafana's address inside the VM (`localhost:3000`), so open Grafana from its tab instead.
""",
        "playground": {
            "networks": [{"name": "local", "subnet": "172.16.0.0/24"}],
            "machines": machines,
            "startupFiles": files,
            "tabs": tabs,
            "initTasks": tasks,
            "accessControl": {"canList": ["anyone"], "canRead": ["anyone"], "canStart": ["anyone"]},
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vms", type=int, default=2, help="number of VMs, 2 to 5 (default: 2)")
    parser.add_argument("--name", default="grafana-alerts-lab-2292969d", help="registered playground name, or a new name for labctl playground create")
    parser.add_argument("--output", type=Path, default=ROOT / "playground/iximiuz/manifest.yaml")
    args = parser.parse_args()
    manifest = render(args.vms, args.name)
    args.output.write_text(
        "# Generated by render_manifest.py; edit the source files instead.\n"
        "# Publish with: bash playground/iximiuz/publish.sh\n" + dump_yaml(manifest) + "\n"
    )
    print(f"Wrote {args.output} for {args.vms} VMs")


if __name__ == "__main__":
    main()
