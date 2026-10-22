# Grafana Alerts Lab

An iximiuz `flexbox` playground with five small metric producing services, Prometheus, Grafana, and a webhook receiver that displays alert notifications. The default layout uses two VMs; the manifest renderer supports two to five VMs.

The [live playground](https://labs.iximiuz.com/playgrounds/grafana-alerts-lab-2292969d) was created from the default two VM manifest.

## Try the incident

1. Start the playground and open **Grafana** and **Alert inbox**. They are placed in separate panes so both can stay visible.
2. In Alert inbox, click **Trigger checkout fault**. The checkout service reports a 75% simulated error ratio and starts counting failed requests.
3. Watch **Service metrics lab** in Grafana. The provisioned alert checks the checkout error ratio every 10 seconds and fires above 20%. Grafana posts a webhook to the receiver on the same VM. The inbox shows a modal popup and a notification record.
4. Click **Restore checkout**. The ratio returns to zero and Grafana sends a resolved notification.

Grafana allows anonymous dashboard viewing. Sign in as `admin` / `lab-demo` to inspect the provisioned alert rule and contact point. Prometheus is available in its own tab; query `up{job="lab-services"}` to see all five targets. The services run on ports 9101 through 9105 and each exposes `/metrics`, `/healthz`, and `/work`.

This is a disposable teaching environment. The service traffic is synthetic, the error ratio is controlled by the fault button, and the inbox keeps notifications in memory for the current VM session.

## Topology

| VM | Default services | Other processes |
| --- | --- | --- |
| `monitor-01` | catalog, checkout, shipping | Prometheus, Grafana, alert inbox |
| `apps-02` | cart, payments | none |

With three to five VMs, the five services are assigned round robin to the requested VMs. Prometheus targets and the inbox's checkout address are generated to match. Each VM has a terminal tab.

## Render or deploy

The checked in [manifest](playground/iximiuz/manifest.yaml) is the two VM default. Render a different layout before deploying:

```bash
python3 playground/iximiuz/render_manifest.py --vms 3
```

The renderer embeds the source files as iximiuz startup files. The monitoring VM uses the official `docker` rootfs; other VMs use `ubuntu-24-04`. Init tasks start the Python services and pull the pinned Prometheus and Grafana images. No custom rootfs publication is needed for this MVP.

With `labctl` installed and authenticated, create a playground or update an existing slug:

```bash
labctl auth login
bash scripts/deploy.sh create 2
bash scripts/deploy.sh update grafana-alerts-lab-2292969d 3
labctl playground start grafana-alerts-lab-2292969d
```

`create` returns the suffixed playground name used for later updates and starts. Updating the definition does not change already running sessions; start a new session to test the new layout. The official iximiuz [manifest reference](https://labs.iximiuz.com/docs/custom-playgrounds/manifest-reference) documents the VM, startup file, init task, and tab fields.

## Files

- [render_manifest.py](playground/iximiuz/render_manifest.py) builds the configurable, self contained playground manifest.
- [service.py](app/service.py) serves the five simulated services and Prometheus metrics.
- [alert_viewer.py](app/alert_viewer.py) receives Grafana webhooks and serves the inbox UI.
- [checkout.yaml](grafana/provisioning/alerting/checkout.yaml) provisions the Grafana alert, webhook contact point, and notification policy.
- [lab.json](grafana/dashboards/lab.json) defines the dashboard.

Grafana provisioning follows the official [file provisioning guide](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/).
