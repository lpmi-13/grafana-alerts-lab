import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "app/alert_viewer.py"
SPEC = importlib.util.spec_from_file_location("alert_viewer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DestinationTests(unittest.TestCase):
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
