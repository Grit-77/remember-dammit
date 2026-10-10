import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo.py"


class DemoTests(unittest.TestCase):
    def test_demo_creates_real_scoped_history_and_current_context(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / "Demo Vault"
            result = subprocess.run([sys.executable, str(DEMO), "--vault", str(vault)],
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            report = json.loads(result.stdout)
            self.assertEqual(report["context"]["provider"], "off")
            self.assertIn("Postmark", json.dumps(report["context"]))
            self.assertNotIn("Use SendGrid", json.dumps(report["context"]))
            self.assertEqual(report["other_project_records"], 0)
            self.assertEqual(report["history_states"], ["superseded", "active"])
            self.assertTrue((vault / ".remember" / "head.json").exists())

    def test_demo_refuses_an_existing_directory_without_changing_its_content(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "owner.txt"
            sentinel.write_text("Keep this content.", encoding="utf-8")
            result = subprocess.run([sys.executable, str(DEMO), "--vault", directory],
                                    capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stdout, "Demo must return a structured refusal.")
            self.assertEqual(json.loads(result.stdout)["error"], "destination_exists")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "Keep this content.")
            self.assertEqual(list(Path(directory).iterdir()), [sentinel])


if __name__ == "__main__":
    unittest.main()
