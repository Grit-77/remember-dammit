import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ExportCommandTests(unittest.TestCase):
    def test_cli_exports_bound_selection_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary).resolve() / "vault"
            snapshot = Path(temporary).resolve() / "snapshot"

            def run(*args):
                return subprocess.run([sys.executable, "-m", "remember_dammit", "--vault", str(vault), *args],
                                      capture_output=True, timeout=30)

            self.assertEqual(run("init").returncode, 0)
            self.assertEqual(run("remember", "--scope", "project:atlas", "--title", "Atlas", "--body", "Visible memory.").returncode, 0)
            self.assertEqual(run("remember", "--scope", "project:beacon", "--title", "Beacon", "--body", "Unrelated fixture.").returncode, 0)
            output = run("export", "--project", "atlas", "--destination", str(snapshot))
            self.assertEqual(output.returncode, 0, output.stdout.decode() + output.stderr.decode())
            result = json.loads(output.stdout)
            self.assertEqual(result["records"], 1)
            self.assertTrue(Path(result["home"]).is_file())
            contents = "\n".join(path.read_text(encoding="utf-8") for path in snapshot.rglob("*.md"))
            self.assertIn("Visible memory.", contents)
            self.assertNotIn("Unrelated fixture.", contents)
            before = {str(p.relative_to(snapshot)): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
            duplicate = run("export", "--project", "atlas", "--destination", str(snapshot))
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual(json.loads(duplicate.stdout)["error"]["code"], "destination_exists")
            self.assertEqual(before, {str(p.relative_to(snapshot)): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
