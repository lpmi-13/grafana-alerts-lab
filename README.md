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

## Send alerts to your own destinations

Alert inbox has a **Your destinations** section. Whatever you save there is added to Grafana's **Lab alerts** contact point next to the inbox webhook, so Grafana notifies both. Grafana picks up changes within about 10 seconds. Add a destination before triggering the fault: Grafana does not resend an alert that is already firing to a replacement webhook URL until the alert resolves.

- **Webhook URL**: one URL, recognized by host. A Discord or Slack webhook URL uses Grafana's Discord or Slack integration. A `https://ntfy.sh/<topic>` URL gets ntfy's `template=grafana` formatting, so subscribing to the topic in the ntfy phone app gives you a push notification. Any other URL receives Grafana's webhook JSON as is.
- **PagerDuty integration key**: the 32 character key from an Events API v2 integration on a PagerDuty service.

Grafana masks Discord, Slack, and PagerDuty secrets, but anonymous Grafana viewers can read a plain webhook URL, so use a hard to guess ntfy topic. Nothing is stored outside the session, and nothing is committed to the manifest.

## Create an alert and webhook directly in the Grafana UI

You can also set up both directly in the Grafana UI. Sign in to the **Grafana** tab as `admin` / `lab-demo`; anonymous viewing cannot save alerting resources.

1. Open **Alerts & IRM → Alerting → Notification configuration → Contact points**. Click **New contact point**, give it a name, select **Webhook**, enter your destination URL, and save it.
2. Open **Alerts & IRM → Alert rules → New alert rule**. Name the rule, select the **Prometheus** data source, and use `lab_service_error_ratio{service="checkout"}` as the query. Set the condition to **is above 0.2**.
3. Choose the **Lab** folder and create a new evaluation group (for example, `my-alerts`) with a 10 second interval. Set the pending period to **None** or `0s`.
4. Under notifications, choose **Select contact point** and select the webhook contact point you just created. Save the rule, then use **Trigger checkout fault** in Alert inbox to test it.

The checkout alert supplied with the lab is file-provisioned, so Grafana displays it as read-only. Create your rule in a new evaluation group. The **Lab alerts** contact point and default notification policy are editable in Grafana too; the inbox uses that contact point for its sample alert. A rule that selects your new contact point directly sends to your webhook without changing the default policy. Creating another checkout rule can produce two notifications for the same fault.

## Topology

| VM | Default services | Other processes |
| --- | --- | --- |
| `monitor-01` | catalog, checkout, shipping | Prometheus, Grafana, alert inbox |
| `apps-02` | cart, payments | none |

With three to five VMs, the five services are assigned round robin to the requested VMs. Prometheus targets and the inbox's checkout address are generated to match. Each VM has a terminal tab.

## How it's deployed on iximiuz Labs

Everything ships in one custom playground, `grafana-alerts-lab-2292969d`, a `flexbox` based playground. [render_manifest.py](playground/iximiuz/render_manifest.py) embeds the app, the Grafana provisioning files, and the dashboard as iximiuz startup files. It also writes the playground's landing page, the manifest's `markdown` field, which walks learners through the incident and through adding a webhook or PagerDuty destination. The monitoring VM uses the official `docker` rootfs; other VMs use `ubuntu-24-04`. Init tasks start the Python services and pull the pinned Prometheus and Grafana images, so there is no custom rootfs image or separate content to publish.

After changing anything, publish with `labctl` installed and authenticated:

```bash
labctl auth login
bash playground/iximiuz/publish.sh
VMS=3 bash playground/iximiuz/publish.sh   # a different layout, 2 to 5 VMs
```

`publish.sh` renders the manifest to a temporary file, runs `labctl playground update`, and only then records the result in the checked in [manifest](playground/iximiuz/manifest.yaml). A failed update leaves the manifest as it was. Set `PLAYGROUND_NAME` to publish to a different playground. Updating the definition does not change running sessions; start a new one to test it:

```bash
labctl playground start grafana-alerts-lab-2292969d
```

To create a new playground instead, render it under an unsuffixed name, create it, and use the suffixed name `labctl` returns as `PLAYGROUND_NAME` from then on:

```bash
python3 playground/iximiuz/render_manifest.py --name grafana-alerts-lab --output /tmp/grafana-alerts-lab.yaml
labctl playground create grafana-alerts-lab --base flexbox -f /tmp/grafana-alerts-lab.yaml
```

The official iximiuz [manifest reference](https://labs.iximiuz.com/docs/custom-playgrounds/manifest-reference) documents the VM, startup file, init task, tab, and `markdown` fields.

## Files

- [render_manifest.py](playground/iximiuz/render_manifest.py) builds the configurable, self contained playground manifest, including its landing page.
- [publish.sh](playground/iximiuz/publish.sh) renders the manifest and updates the playground on iximiuz Labs.
- [service.py](app/service.py) serves the five simulated services and Prometheus metrics.
- [alert_viewer.py](app/alert_viewer.py) receives Grafana webhooks, serves the inbox UI, and manages the **Lab alerts** contact point and notification policy through Grafana's provisioning API. Resources provisioned from files cannot be changed through that API, so these are created at runtime.
- [checkout.yaml](grafana/provisioning/alerting/checkout.yaml) provisions the Grafana alert rule.
- [lab.json](grafana/dashboards/lab.json) defines the dashboard.

Grafana provisioning follows the official [file provisioning guide](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/).
