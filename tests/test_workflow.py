"""End-to-end core workflows using real committed Markdown and search."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from remember_dammit.storage import Vault
from remember_dammit.retrieval import context, encode_packet, reindex, search
from remember_dammit.errors import VaultError


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        cache = patch.dict(os.environ, {"REMEMBER_DAMMIT_STATE_HOME": str(self.base / "cache")})
        cache.start()
        self.addCleanup(cache.stop)
        self.root = self.base / "My Vault"
        self.vault = Vault.initialize(self.root)

    def test_source_correction_and_reopen_follow_the_current_decision(self):
        source = self.vault.put(title="Original brief", body="Use SendGrid for transactional email.", scope="project:atlas", kind="source")
        first = self.vault.put(title="Email choice", body="Use SendGrid for Atlas.", scope="project:atlas", sources=[source["id"]])
        change = self.vault.put(title="Explicit correction", body="Use Postmark instead of SendGrid.", scope="project:atlas", kind="source")
        current = self.vault.correct(first["id"], expected_revision=first["revision"], title="Email choice", body="Use Postmark for Atlas.", sources=[change["id"]])
        reopened = Vault(self.root)
        results = search(reopened, "SendGrid", project="atlas")
        ids = [item["id"] for item in results["records"]]
        self.assertIn(current["id"], ids)
        self.assertNotIn(first["id"], ids)
        decision = next(item for item in results["records"] if item["id"] == current["id"])
        self.assertEqual(decision["sources"][0]["id"], change["id"])
        self.assertEqual([entry["state"] for entry in reopened.history(first["id"])], ["superseded", "active"])
        self.assertEqual(search(reopened, "SendGrid", project="beacon")["records"], [])

    def test_context_does_not_reintroduce_obsolete_instruction_through_raw_source(self):
        old_source = self.vault.put(title="Initial brief", body="Use SendGrid.", scope="project:atlas", kind="source")
        old = self.vault.put(title="Provider", body="Use SendGrid.", scope="project:atlas", sources=[old_source["id"]])
        new_source = self.vault.put(title="Correction", body="Use Postmark now.", scope="project:atlas", kind="source")
        current = self.vault.correct(old["id"], expected_revision=old["revision"], title="Provider", body="Use Postmark now.", sources=[new_source["id"]])
        packet = context(self.vault, "SendGrid", project="atlas", budget_bytes=8000)
        self.assertIn(current["id"], [r["id"] for r in packet["records"]])
        self.assertNotIn("Use SendGrid.", encode_packet(packet))
        # Explicit history search may expose the historical source as evidence.
        history = search(self.vault, "SendGrid", project="atlas", include_history=True)
        self.assertIn(old_source["id"], [r["id"] for r in history["records"]])

    def test_personal_grant_is_live_and_never_exports_to_other_projects(self):
        note = self.vault.put(title="Writing", body="Prefer concise replies with citations.", scope="personal")
        self.assertEqual(search(self.vault, "concise", project="atlas")["records"], [])
        self.vault.grant("atlas", note["id"])
        self.assertEqual(search(self.vault, "concise", project="atlas")["records"][0]["id"], note["id"])
        self.assertEqual(search(self.vault, "concise", project="beacon")["records"], [])
        self.vault.revoke("atlas", note["id"])
        self.assertEqual(search(Vault(self.root), "concise", project="atlas")["records"], [])

    def test_four_actors_share_ids_and_keep_independent_session_cards(self):
        for actor in ("claude", "codex", "cursor", "antigravity"):
            self.vault.put(title=f"Session {actor}", body=f"Continue fixture work from {actor}.", scope="project:atlas", kind="session", actor=actor)
        reopened = Vault(self.root)
        sessions = search(reopened, "fixture", project="atlas")["records"]
        self.assertEqual(len(sessions), 4)
        self.assertEqual(len({item["id"] for item in sessions}), 4)
        self.assertEqual({r["actor"] for r in reopened.list_records()}, {"claude", "codex", "cursor", "antigravity"})
        # Actor strings demonstrate shared storage only, not live client compatibility.

    def test_index_loss_changes_neither_context_nor_source_history(self):
        self.vault.put(title="Memory", body="Keep the small useful source.", scope="project:atlas")
        first = context(self.vault, "source", project="atlas", budget_bytes=4000)
        projection = reindex(self.vault)
        Path(projection["path"]).unlink()
        reindex(Vault(self.root))
        self.assertEqual(encode_packet(context(self.vault, "source", project="atlas", budget_bytes=4000)), encode_packet(first))

    def test_external_edit_is_visible_as_integrity_failure_never_stale_recall(self):
        record = self.vault.put(title="Decision", body="Use original setting.", scope="project:atlas")
        path = self.root / record["path"]
        path.write_text(path.read_text(encoding="utf-8").replace("Use original setting.", "Use external edit."), encoding="utf-8")
        with self.assertRaises(VaultError) as error:
            context(self.vault, "setting", project="atlas")
        self.assertEqual(error.exception.code, "integrity_error")
        self.assertFalse(self.vault.doctor()["ok"])


if __name__ == "__main__":
    unittest.main()
