"""Behavioral fixtures for scope-safe lexical recall and complete context budgets."""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from remember_dammit import retrieval

from remember_dammit.errors import VaultError


def record(identifier, body, *, scope="project:atlas", **extra):
    item = dict(id=identifier, revision=hashlib.sha256(body.encode()).hexdigest(),
                title=identifier, body=body, scope=scope, kind="note", state="active",
                sources=[], aliases=[], supersedes=None, evidence="user-statement",
                disclosure="private", remote_allowed=False, actor="fixture",
                created_at="2026-10-10T00:00:00Z", path=f"Notes/{identifier}.md")
    item.update(extra)
    return item


class Corpus:
    """A finite immutable-record/policy input, not a mocked search implementation."""

    vault_id = "synthetic-vault"

    def __init__(self, records, root):
        self.records = records
        self.root = Path(root)
        self.grants = set()

    def list_records(self):
        return copy.deepcopy(self.records)

    def grants_for(self, project):
        return set(self.grants) if project == "atlas" else set()

    def snapshot_id(self):
        value = json.dumps([self.records, sorted(self.grants)], sort_keys=True)
        return hashlib.sha256(value.encode()).hexdigest()


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = patch.dict(os.environ, {"REMEMBER_DAMMIT_STATE_HOME": self.temp.name})
        self.cache.start()
        self.addCleanup(self.cache.stop)

    def corpus(self, records):
        return Corpus(records, self.temp.name)

    def test_project_filters_before_ranking_and_revocation_takes_effect(self):
        vault = self.corpus([record("atlas", "email"),
                             record("secret", "email email hidden beacon", scope="project:beacon"),
                             record("style", "email concise", scope="personal")])
        vault.grants.add("style")
        result = retrieval.search(vault, "email", project="atlas")
        self.assertEqual({r["id"] for r in result["records"]}, {"atlas", "style"})
        self.assertNotIn("hidden beacon", json.dumps(result))
        vault.grants.clear()
        self.assertEqual([r["id"] for r in retrieval.search(vault, "concise", project="atlas")["records"]], [])
        self.assertFalse(retrieval.visible_record(vault, vault.records[1], project="atlas"))

    def test_old_search_terms_find_current_correction_without_old_instruction(self):
        vault = self.corpus([record("old", "Use SendGrid for email", state="superseded"),
                             record("new", "Use Postmark for email", supersedes="old")])
        result = retrieval.search(vault, "SendGrid", project="atlas")
        self.assertEqual([r["id"] for r in result["records"]], ["new"])
        self.assertEqual(result["records"][0]["body"], "Use Postmark for email")
        self.assertIn("supersession", result["records"][0]["reason"])
        self.assertNotIn("Use SendGrid", json.dumps(result))

    def test_late_passage_is_returned_with_exact_current_source_offsets(self):
        text = "# Background\n" + ("unrelated background. " * 150) + "\n\n# Decision\nThe retry timeout is 17 seconds."
        vault = self.corpus([record("source", text, kind="source")])
        item = retrieval.search(vault, "timeout", project="atlas")["records"][0]
        self.assertIn("17 seconds", item["body"])
        citation = item["citation"]
        self.assertEqual(text[citation["start"]:citation["end"]], item["body"])
        self.assertLess(len(item["body"]), 500)
        self.assertEqual(citation["revision"], vault.records[0]["revision"])

    def test_unicode_alias_recall_and_unknown_query_abstain(self):
        vault = self.corpus([record("language", "İçerik Türkçe olabilir.", aliases=["çalışma biçimi"])])
        self.assertEqual(len(retrieval.search(vault, "CALISMA", project="atlas")["records"]), 1)
        miss = retrieval.search(vault, "platypus", project="atlas")
        self.assertEqual(miss["records"], [])
        self.assertEqual(miss["status"], "no_results")
        self.assertEqual(retrieval.search(vault, '"* OR ()', project="atlas")["records"], [])

    def test_audience_filter_does_not_leak_private_source_of_public_claim(self):
        vault = self.corpus([record("secret", "ultraviolet account source"),
                             record("claim", "email decision", disclosure="public", sources=["secret"]),
                             record("public", "email help", disclosure="public")])
        result = retrieval.search(vault, "email", project="atlas", audience="public")
        self.assertEqual([r["id"] for r in result["records"]], ["public"])
        self.assertNotIn("secret", json.dumps(result))

    def test_selection_is_explicit_and_proposed_records_are_not_facts(self):
        vault = self.corpus([record("idea", "email", state="proposed")])
        for options in ({}, {"project": "atlas", "personal": True}):
            with self.assertRaises(VaultError) as error:
                retrieval.search(vault, "email", **options)
            self.assertEqual(error.exception.code, "invalid_scope")
        self.assertEqual(retrieval.search(vault, "email", project="atlas")["records"], [])

    def test_project_identifiers_match_portable_storage_rules(self):
        identifier = "a" * 128
        vault = self.corpus([record("email", "email", scope="project:" + identifier)])
        try:
            result = retrieval.search(vault, "email", project=identifier)
        except VaultError as error:
            self.fail(f"A valid storage scope was rejected by recall: {error.code}")
        self.assertEqual(len(result["records"]), 1)
        for invalid in ("CON", "nul.txt", "COM1", "trailing.", "a" * 129):
            with self.assertRaises(VaultError) as error:
                retrieval.search(vault, "email", project=invalid)
            self.assertEqual(error.exception.code, "invalid_scope")

    def test_complete_utf8_packet_obeys_budget_and_discloses_omissions(self):
        vault = self.corpus([record("short", "email kısa özet"),
                             record("long", "email " + ("界" * 1000))])
        packet = retrieval.context(vault, "email", project="atlas", budget_bytes=1500)
        encoded = retrieval.encode_packet(packet)
        self.assertLessEqual(len(encoded.encode("utf-8")), 1500)
        self.assertEqual(len(packet["records"]), 1)
        self.assertEqual(packet["records"][0]["id"], "short")
        self.assertGreater(packet["omitted"]["budget"], 0)
        self.assertEqual(json.loads(encoded), packet)
        with self.assertRaises(VaultError) as error:
            retrieval.context(vault, "email", project="atlas", budget_bytes=10)
        self.assertEqual(error.exception.code, "budget_too_small")

    def test_conflicting_successors_are_never_packaged_as_a_single_settled_choice(self):
        vault = self.corpus([record("base", "email provider", state="superseded"),
                             record("left", "Use Postmark", supersedes="base"),
                             record("right", "Use SES", supersedes="base")])
        packet = retrieval.context(vault, "Postmark", project="atlas", budget_bytes=8000)
        self.assertEqual({r["id"] for r in packet["records"]}, {"left", "right"})
        self.assertTrue(packet["warnings"])
        for item in packet["records"]:
            self.assertTrue(item["conflicts_with"])

    def test_rebuildable_projection_does_not_write_inside_vault(self):
        root = Path(self.temp.name) / "vault"
        root.mkdir()
        vault = Corpus([record("email", "email choice")], root)
        report = retrieval.reindex(vault)
        self.assertEqual(report["records"], 1)
        index = Path(report["path"])
        self.assertTrue(index.is_file())
        self.assertFalse(index.is_relative_to(root))
        index.unlink()
        self.assertEqual(retrieval.reindex(vault)["records"], 1)
        self.assertEqual(retrieval.search(vault, "email", project="atlas")["records"][0]["id"], "email")


if __name__ == "__main__":
    unittest.main()
