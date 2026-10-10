"""CLI behavior exercised through the installed Python module and real vaults."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "vault"

    def run_cli(self, *arguments):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1", REMEMBER_DAMMIT_STATE_HOME=str(Path(self.temp.name) / "local-state"))
        return subprocess.run(
            [sys.executable, "-m", "remember_dammit", "--vault", str(self.vault), *arguments],
            capture_output=True, env=env, cwd=ROOT, timeout=30,
        )

    def ok(self, *arguments):
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr.decode() + result.stdout.decode())
        return json.loads(result.stdout)

    def test_init_and_remember_persist_across_processes(self):
        self.ok("init")
        record = self.ok("remember", "--scope", "project:atlas", "--title", "Mail", "--body", "Use Postmark", "--alias", "email")
        shown = self.ok("show", record["id"])
        self.assertEqual(shown["body"], "Use Postmark")
        self.assertEqual(shown["scope"], "project:atlas")
        self.assertEqual(shown["aliases"], ["email"])

    def test_domain_error_is_json_without_traceback(self):
        self.ok("init")
        result = self.run_cli("show", "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", json.loads(result.stdout))
        self.assertNotIn(b"Traceback", result.stderr + result.stdout)

    def test_argument_errors_are_json(self):
        result = self.run_cli("recall", "mail")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_arguments")
        self.assertEqual(result.stderr, b"")

    def test_context_stdout_has_no_trailing_bytes_and_respects_utf8_budget(self):
        self.ok("init")
        self.ok("remember", "--scope", "project:atlas", "--title", "Mail", "--body", "İstanbul " * 20)
        result = self.run_cli("context", "Mail", "--project", "atlas", "--budget-bytes", "1200")
        self.assertEqual(result.returncode, 0, result.stdout.decode())
        packet = json.loads(result.stdout)
        self.assertIsInstance(packet, dict)
        self.assertTrue(result.stdout.endswith(b"}"))
        self.assertLessEqual(len(result.stdout), 1200)

    def test_context_reports_error_when_complete_passage_cannot_fit(self):
        self.ok("init")
        self.ok("remember", "--scope", "project:atlas", "--title", "Mail", "--body", "İstanbul " * 500)
        result = self.run_cli("context", "Mail", "--project", "atlas", "--budget-bytes", "1200")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "budget_too_small")

    def test_correct_history_and_stale_revision_error(self):
        self.ok("init")
        first = self.ok("remember", "--scope", "personal", "--title", "Editor", "--body", "Vim")
        second = self.ok("correct", first["id"], "--expected-revision", first["revision"], "--title", "Editor", "--body", "Emacs")
        history = self.ok("history", second["id"])
        self.assertEqual([r["body"] for r in history], ["Vim", "Emacs"])
        result = self.run_cli("correct", first["id"], "--expected-revision", "wrong", "--title", "Editor", "--body", "Nano")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", json.loads(result.stdout))

    def test_grant_revoke_and_recall_project_selection(self):
        self.ok("init")
        record = self.ok("remember", "--scope", "personal", "--title", "Unique personal", "--body", "Telescope secret")
        self.assertNotIn("Telescope secret", json.dumps(self.ok("recall", "Telescope", "--project", "atlas")))
        self.ok("grant", "atlas", record["id"])
        self.assertIn("Telescope secret", json.dumps(self.ok("recall", "Telescope", "--project", "atlas")))
        self.ok("revoke", "atlas", record["id"])
        self.assertNotIn("Telescope secret", json.dumps(self.ok("recall", "Telescope", "--project", "atlas")))

    def test_doctor_and_reindex_emit_json(self):
        self.ok("init")
        self.assertIsInstance(self.ok("doctor"), dict)
        self.assertIsInstance(self.ok("reindex"), dict)

    def test_integration_outputs_proposal_only(self):
        proposal = self.ok("integration", "codex", "--project", "atlas")
        self.assertEqual(proposal["harness"], "codex")
        self.assertFalse(proposal["tested_live"])
        self.assertIn("config_text", proposal)
        self.assertFalse(self.vault.exists())


if __name__ == "__main__":
    unittest.main()
