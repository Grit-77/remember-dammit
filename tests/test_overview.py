"""Queryless navigation against real, committed temporary vaults."""

import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


class OverviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Vault.initialize(Path(temporary.name) / "vault")

    def overview(self, **selection):
        try:
            module = importlib.import_module("remember_dammit.overview")
        except ModuleNotFoundError:
            self.fail("The read-only overview is not implemented")
        return module.overview(self.vault, **selection)

    def put(self, identifier, **metadata):
        return self.vault.put(record_id=identifier, title=identifier + " title",
                              body="Body must never be included", scope=metadata.pop("scope", "project:atlas"),
                              **metadata)

    def test_scope_first_selection_and_audience_do_not_leak_foreign_metadata(self):
        self.put("atlas-private", kind="task")
        self.put("atlas-public", disclosure="public")
        self.put("shared", scope="shared", disclosure="shared")
        self.put("personal", scope="personal")
        self.put("foreign", scope="project:beacon")
        self.put("session", scope="session:atlas")
        result = self.overview(project="atlas")
        self.assertEqual([r["id"] for r in result["records"]], ["atlas-private", "atlas-public", "shared"])
        self.assertEqual(result["selection"], {"project": "atlas", "personal": False,
                                               "scope": "project:atlas", "audience": "private"})
        self.assertEqual(result["summary"], {"by_kind": {"note": 2, "task": 1}, "by_state": {"active": 3}})
        self.assertEqual([r["id"] for r in self.overview(project="atlas", audience="shared")["records"]], ["atlas-public", "shared"])
        self.assertEqual([r["id"] for r in self.overview(project="atlas", audience="public")["records"]], ["atlas-public"])
        self.assertEqual([r["id"] for r in self.overview(personal=True)["records"]], ["personal", "shared"])
        encoded = json.dumps(result)
        for forbidden in ("foreign", "personal title", "session", "Body must never"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(result["snapshot"], self.vault.snapshot_id())

    def test_grant_revocation_blocks_transitive_sources_without_hidden_ids_or_titles(self):
        self.put("private-source", scope="personal", kind="source")
        self.vault.grant("atlas", "private-source")
        self.put("derived", sources=["private-source"])
        self.put("indirect", sources=["derived"])
        self.put("independent")
        before = self.overview(project="atlas")
        self.assertEqual(before["total_count"], 4)
        self.vault.revoke("atlas", "private-source")
        after = self.overview(project="atlas")
        self.assertEqual([r["id"] for r in after["records"]], ["independent"])
        self.assertEqual(after["omitted"]["source_dependencies"], 2)
        self.assertEqual(after["summary"], {"by_kind": {"note": 1}, "by_state": {"active": 1}})
        for forbidden in ("private-source", "derived", "indirect"):
            self.assertNotIn(forbidden, json.dumps(after))

    def test_exact_sources_and_backlinks_are_metadata_only_and_ignore_body_links(self):
        source = self.put("a-source", kind="source")
        note = self.vault.put(record_id="b-note", title="Decision", body="[fake](c-other) a-source",
                              scope="project:atlas", sources=[source["id"]])
        self.put("c-other")
        result = self.overview(project="atlas")
        records = {r["id"]: r for r in result["records"]}
        self.assertEqual(records["a-source"]["backlinks"], [{"id": "b-note", "revision": note["revision"],
                          "title": "Decision", "kind": "note", "state": "active", "scope": "project:atlas"}])
        self.assertEqual([r["id"] for r in records["b-note"]["sources"]], ["a-source"])
        self.assertEqual(records["c-other"]["backlinks"], [])
        for record in records.values():
            self.assertNotIn("body", record)
            self.assertNotIn("path", record)
            self.assertNotIn("aliases", record)
            self.assertNotIn("supersedes", record)

    def test_proposed_review_and_task_are_explicit_metadata_without_inferred_status(self):
        self.put("review", state="proposed", kind="review", evidence="agent-inference")
        self.vault.put(record_id="task", title="Work", body="Completed yesterday; due tomorrow",
                       scope="project:atlas", kind="task")
        result = self.overview(project="atlas")
        self.assertEqual(result["summary"], {"by_kind": {"review": 1, "task": 1},
                                            "by_state": {"active": 1, "proposed": 1}})
        review, task = result["records"]
        self.assertEqual((review["state"], review["evidence"]), ("proposed", "agent-inference"))
        self.assertEqual((task["kind"], task["state"]), ("task", "active"))
        self.assertNotIn("due", json.dumps(result))
        self.assertNotIn("completed", json.dumps(result))

    def test_limit_counts_all_safe_records_and_links_to_unpaged_visible_records(self):
        self.put("c-source", kind="source")
        self.put("a-note", sources=["c-source"])
        self.put("b-note")
        result = self.overview(project="atlas", limit=1)
        self.assertEqual([r["id"] for r in result["records"]], ["a-note"])
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["summary"], {"by_kind": {"note": 2, "source": 1}, "by_state": {"active": 3}})
        self.assertEqual(result["omitted"], {"limit": 2, "source_dependencies": 0})
        self.assertEqual(result["records"][0]["sources"][0]["id"], "c-source")

    def test_correction_hides_old_head_and_historical_only_source(self):
        self.put("old-source", kind="source")
        old = self.put("old-head", sources=["old-source"])
        self.put("new-source", kind="source")
        new = self.vault.correct(old["id"], expected_revision=old["revision"],
                                 title="Current choice", body="New body", sources=["new-source"])
        result = self.overview(project="atlas")
        self.assertEqual({r["id"] for r in result["records"]}, {"new-source", new["id"]})
        self.assertNotIn("old-head", json.dumps(result))
        self.assertNotIn("old-source", json.dumps(result))

    def test_proposed_reference_keeps_its_still_active_source_after_correction(self):
        self.put("old-source", kind="source")
        old = self.put("old-head", sources=["old-source"])
        self.put("proposal", sources=["old-source"], state="proposed", evidence="agent-inference")
        self.vault.correct(old["id"], expected_revision=old["revision"], title="Current choice",
                           body="New body", sources=[])
        result = self.overview(project="atlas")
        records = {r["id"]: r for r in result["records"]}
        self.assertIn("old-source", records)
        self.assertEqual(records["proposal"]["sources"][0]["id"], "old-source")

    def test_public_audience_blocks_private_dependencies_and_their_descendants(self):
        self.put("private-source", kind="source")
        self.put("public-derived", disclosure="public", sources=["private-source"])
        self.put("public-indirect", disclosure="public", sources=["public-derived"])
        result = self.overview(project="atlas", audience="public")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["omitted"]["source_dependencies"], 2)
        for hidden in ("private-source", "public-derived", "public-indirect"):
            self.assertNotIn(hidden, json.dumps(result))

    def test_corrected_source_blocks_records_still_citing_its_inactive_head(self):
        old = self.put("old-source", kind="source")
        self.put("dependent", sources=[old["id"]])
        self.put("indirect", sources=["dependent"])
        new = self.vault.correct(old["id"], expected_revision=old["revision"],
                                 title="Current evidence", body="New source")
        result = self.overview(project="atlas")
        self.assertEqual([r["id"] for r in result["records"]], [new["id"]])
        self.assertEqual(result["omitted"]["source_dependencies"], 2)
        for hidden in ("old-source", "dependent", "indirect"):
            self.assertNotIn(hidden, json.dumps(result))

    def test_source_and_backlink_lists_are_bounded_with_explicit_omissions(self):
        for number in range(23):
            self.put(f"s{number:02}", kind="source")
        self.put("a-many-sources", sources=[f"s{number:02}" for number in reversed(range(23))])
        for number in range(23):
            self.put(f"n{number:02}", sources=["s00"])
        result = self.overview(project="atlas")
        records = {r["id"]: r for r in result["records"]}
        note = records["a-many-sources"]
        self.assertEqual([r["id"] for r in note["sources"]], [f"s{number:02}" for number in range(20)])
        self.assertEqual(note["omitted"], {"sources": 3, "backlinks": 0})
        source = records["s00"]
        self.assertEqual([r["id"] for r in source["backlinks"]], ["a-many-sources", *[f"n{number:02}" for number in range(19)]])
        self.assertEqual(source["omitted"], {"sources": 0, "backlinks": 4})

    def test_delivery_rechecks_freshness_after_real_revocation(self):
        self.put("private-source", scope="personal")
        self.vault.grant("atlas", "private-source")
        original = self.vault.snapshot_id
        calls = 0
        def snapshot():
            nonlocal calls
            calls += 1
            if calls == 3:
                self.vault.revoke("atlas", "private-source")
            return original()
        with patch.object(self.vault, "snapshot_id", side_effect=snapshot):
            with self.assertRaises(VaultError) as error:
                self.overview(project="atlas")
        self.assertEqual(error.exception.code, "source_changed")

    def test_read_only_empty_result_and_invalid_selection(self):
        before = {str(p.relative_to(self.vault.root)): p.read_bytes()
                  for p in self.vault.root.rglob("*") if p.is_file()}
        result = self.overview(personal=True)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["summary"], {"by_kind": {}, "by_state": {}})
        self.assertEqual(result["status"], "no_results")
        self.assertEqual(before, {str(p.relative_to(self.vault.root)): p.read_bytes()
                                 for p in self.vault.root.rglob("*") if p.is_file()})
        for selection in ({}, {"project": "atlas", "personal": True}, {"project": "../bad"},
                          {"personal": "yes"}, {"personal": True, "audience": "unknown"},
                          *({"personal": True, "limit": n} for n in (0, 101, True, "1", None))):
            with self.subTest(selection=selection), self.assertRaises(VaultError):
                self.overview(**selection)


if __name__ == "__main__":
    unittest.main()
