import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "app/alert_viewer.py"
SPEC = importlib.util.spec_from_file_location("alert_viewer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DestinationTests(unittest.TestCase):
    def test_api_created_resources_are_editable_in_grafana(self):
        requests = []

        def respond(request, timeout):
            requests.append(request)
            return io.BytesIO(b"{}")

        with mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=respond):
            MODULE.grafana("POST", "/contact-points", MODULE.INBOX)
            MODULE.grafana("PUT", "/policies", MODULE.POLICY)
            MODULE.grafana("GET", "/policies")

        self.assertEqual([request.get_header("X-disable-provenance") for request in requests], ["true", "true", None])

    def test_restart_keeps_policies_edited_in_grafana(self):
        for receiver in ("Lab alerts", "My webhook", "empty"):
            with self.subTest(receiver=receiver):
                calls = []

                def grafana(method, path, body=None):
                    calls.append((method, path))
                    if path == "/contact-points?name=Lab%20alerts":
                        return [MODULE.INBOX]
                    if path == "/policies":
                        return {"receiver": receiver, "routes": [{"receiver": "Another destination"}]}
                    raise AssertionError((method, path))

                with mock.patch.object(MODULE, "grafana", side_effect=grafana):
                    MODULE.ensure_routing()

                self.assertEqual(calls, [("GET", "/contact-points?name=Lab%20alerts"), ("GET", "/policies")])

    def test_new_grafana_routes_to_the_inbox(self):
        calls = []

        def grafana(method, path, body=None):
            calls.append((method, path))
            if path == "/contact-points?name=Lab%20alerts":
                return []
            if method == "GET" and path == "/policies":
                return {"receiver": "empty"}
            return None

        with mock.patch.object(MODULE, "grafana", side_effect=grafana):
            MODULE.ensure_routing()

        self.assertEqual(calls, [
            ("GET", "/contact-points?name=Lab%20alerts"),
            ("POST", "/contact-points"),
            ("GET", "/policies"),
            ("PUT", "/policies"),
        ])

    def test_webhook_urls_choose_the_matching_integration(self):
        cases = {
            "https://discord.com/api/webhooks/1/abc": ("discord", "https://discord.com/api/webhooks/1/abc"),
            "https://hooks.slack.com/services/T/B/x": ("slack", "https://hooks.slack.com/services/T/B/x"),
            "https://ntfy.sh/lab-topic": ("webhook", "https://ntfy.sh/lab-topic?template=grafana"),
            "https://ntfy.sh/lab-topic?priority=4": ("webhook", "https://ntfy.sh/lab-topic?priority=4&template=grafana"),
            "https://ntfy.sh/lab-topic?tpl=yes&m=hi": ("webhook", "https://ntfy.sh/lab-topic?tpl=yes&m=hi"),
            " https://webhook.site/abc ": ("webhook", "https://webhook.site/abc"),
        }
        for url, (integration_type, sent_url) in cases.items():
            with self.subTest(url=url):
                result_type, settings = MODULE.webhook_integration(url)
                self.assertEqual(result_type, integration_type)
                self.assertEqual(settings["url"], sent_url)

    def test_invalid_webhook_urls_are_rejected(self):
        for url in ("", "ntfy.sh/topic", "ftp://example.com/hook", "https://", None, "https://x.io/" + "a" * 2000):
            with self.subTest(url=url), self.assertRaises(ValueError):
                MODULE.webhook_integration(url)

    def test_pagerduty_key_must_be_32_letters_and_digits(self):
        self.assertEqual(MODULE.pagerduty_integration(" " + "a1" * 16 + "\n"), ("pagerduty", {"integrationKey": "a1" * 16}))
        for key in ("", "a" * 31, "a" * 33, "a" * 31 + "-", None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                MODULE.pagerduty_integration(key)


if __name__ == "__main__":
    unittest.main()
