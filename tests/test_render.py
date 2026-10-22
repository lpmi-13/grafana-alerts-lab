import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "playground/iximiuz/render_manifest.py"
SPEC = importlib.util.spec_from_file_location("render_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ManifestTests(unittest.TestCase):
    def test_every_supported_vm_count_has_five_scrape_targets(self):
        for count in range(2, 6):
            with self.subTest(vms=count):
                manifest = MODULE.render(count, "test-lab")
                playground = manifest["playground"]
                machines = playground["machines"]
                self.assertEqual(len(machines), count)
                self.assertEqual(len(playground["startupFiles"]), 10)
                self.assertEqual(len(playground["initTasks"]), count)
                self.assertLessEqual(sum(machine["resources"]["cpuCount"] for machine in machines), 5)
                prometheus = next(f["content"] for f in playground["startupFiles"] if f["path"].endswith("prometheus.yml"))
                for index, service in enumerate(MODULE.SERVICES):
                    ip = f"172.16.0.{index % count + 2}"
                    port = MODULE.PORTS[service]
                    self.assertIn(f"{ip}:{port}", prometheus)
                    task = playground["initTasks"][f"init_{machines[index % count]['name'].replace('-', '_')}"]
                    self.assertIn(f"lab-service@{service}.service", task["run"])

    def test_out_of_range_vm_count_is_rejected(self):
        for count in (1, 6):
            with self.assertRaises(ValueError):
                MODULE.render(count, "test-lab")


if __name__ == "__main__":
    unittest.main()
