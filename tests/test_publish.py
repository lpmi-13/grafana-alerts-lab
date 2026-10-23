"""Exercise publishing with a fake labctl command."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_MANIFEST = "# previously published manifest\n"


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for source in ("app", "grafana"):
            shutil.copytree(ROOT / source, self.root / source)
        scripts = self.root / "playground" / "iximiuz"
        scripts.mkdir(parents=True)
        for name in ("publish.sh", "render_manifest.py"):
            shutil.copy2(ROOT / "playground" / "iximiuz" / name, scripts / name)
        self.manifest = scripts / "manifest.yaml"

        mock_bin = self.root / "mock-bin"
        mock_bin.mkdir()
        stub = mock_bin / "labctl"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['CALL_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(args) + '\\n')\n"
            "if args[:2] == ['playground', 'update']:\n"
            "    shutil.copy2(args[args.index('-f') + 1], os.environ['CAPTURE_MANIFEST'])\n"
            "if os.environ.get('FAIL_AT') == args[0]:\n"
            "    sys.exit(1)\n"
        )
        stub.chmod(0o755)
        self.log = self.root / "calls.jsonl"
        self.capture = self.root / "sent-manifest.yaml"
        self.env = os.environ | {
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "CALL_LOG": str(self.log),
            "CAPTURE_MANIFEST": str(self.capture),
        }

    def publish(self, **env):
        self.log.write_text("")
        self.manifest.write_text(OLD_MANIFEST)
        result = subprocess.run(
            ["bash", str(self.root / "playground" / "iximiuz" / "publish.sh")],
            cwd=self.root,
            env=self.env | env,
            capture_output=True,
            text=True,
        )
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return result, calls

    def leftover_temp_files(self):
        return list(self.manifest.parent.glob("manifest.yaml.next.*"))

    def test_publish_updates_playground_then_records_manifest(self):
        result, calls = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1][:3], ["playground", "update", "grafana-alerts-lab-2292969d"])
        self.assertEqual(self.manifest.read_text(), self.capture.read_text())
        published = self.manifest.read_text()
        self.assertIn('name: "grafana-alerts-lab-2292969d"', published)
        self.assertIn("## Send the alert to your own destination", published)
        self.assertEqual(published.count('id: "terminal-'), 2)
        self.assertEqual(self.leftover_temp_files(), [])

    def test_name_and_vm_count_can_be_overridden(self):
        result, calls = self.publish(PLAYGROUND_NAME="other-lab-1234", VMS="3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1][:3], ["playground", "update", "other-lab-1234"])
        self.assertIn('name: "other-lab-1234"', self.manifest.read_text())
        self.assertEqual(self.manifest.read_text().count('id: "terminal-'), 3)

    def test_failed_playground_update_does_not_advance_manifest(self):
        result, _ = self.publish(FAIL_AT="playground")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.manifest.read_text(), OLD_MANIFEST)
        self.assertEqual(self.leftover_temp_files(), [])

    def test_logged_out_publish_stops_before_update(self):
        result, calls = self.publish(FAIL_AT="auth")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("labctl auth login", result.stderr)
        self.assertFalse(any(call[:2] == ["playground", "update"] for call in calls))
        self.assertEqual(self.manifest.read_text(), OLD_MANIFEST)

    def test_invalid_vm_count_stops_before_labctl(self):
        result, calls = self.publish(VMS="6")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual(self.manifest.read_text(), OLD_MANIFEST)
        self.assertEqual(self.leftover_temp_files(), [])


if __name__ == "__main__":
    unittest.main()
