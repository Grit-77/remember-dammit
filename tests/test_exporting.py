"""Real-vault, source-safe Markdown snapshot export boundaries."""

import importlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.vault = Vault.initialize(self.root / "vault")

    def export(self, destination, **selection):
        try:
            module = importlib.import_module("remember_dammit.exporting")
        except ModuleNotFoundError:
            self.fail("The snapshot exporter is not implemented")
        return module.export_snapshot(self.vault, destination, **selection)

    def notes(self, destination):
        result = {}
        for path in (destination / "notes").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            _, metadata, remainder = text.split("---\n", 2)
            data = yaml.safe_load(metadata)
            result[data["id"]] = (data, remainder, path)
        return result

    def all_text(self, destination):
        return "\n".join(path.read_text(encoding="utf-8") for path in destination.rglob("*.md"))

    def test_grants_revocation_and_transitive_source_filtering_never_leak(self):
        source = self.vault.put(title="REVOKED SOURCE TITLE", body="private-source-text", scope="personal", kind="source", record_id="private-source-id")
        self.vault.grant("atlas", source["id"])
        derived = self.vault.put(title="Derived decision", body="derived-secret", scope="project:atlas", sources=[source["id"]], record_id="derived-id")
        chain = self.vault.put(title="Indirect decision", body="indirect-secret", scope="project:atlas", sources=[derived["id"]], record_id="indirect-id")
        shared = self.vault.put(title="Shared source", body="shared-text", scope="shared", record_id="shared-id")
        self.vault.put(title="SIBLING TITLE", body="sibling-secret", scope="project:beacon", record_id="sibling-id")
        self.vault.put(title="SESSION TITLE", body="session-secret", scope="session:other", record_id="session-id")
        before = self.root / "before"
        self.export(before, project="atlas")
        self.assertEqual(set(self.notes(before)), {source["id"], derived["id"], chain["id"], shared["id"]})
        self.vault.revoke("atlas", source["id"])
        after = self.root / "after"
        self.export(after, project="atlas", include_history=True)
        self.assertEqual(set(self.notes(after)), {shared["id"]})
        text = self.all_text(after)
        for hidden in ("REVOKED SOURCE TITLE", "private-source-text", "private-source-id", "derived-id", "derived-secret", "indirect-id", "indirect-secret", "SIBLING TITLE", "sibling-secret", "sibling-id", "session-secret", "session-id"):
            self.assertNotIn(hidden, text)
        personal = self.root / "personal"
        self.export(personal, personal=True)
        self.assertEqual(set(self.notes(personal)), {source["id"], shared["id"]})

    def test_yaml_metadata_links_and_utf8_body_snapshot_preserve_live_bytes(self):
        source = self.vault.put(title='Source: "quoted" [label]', body="Evidence İ\nline\n\nfinal", scope="project:atlas", kind="source")
        note = self.vault.put(title="Decision ](broken)\nsecond", body="# Body\nUse café.\n\n---\nOriginal body remains intact.", scope="project:atlas", sources=[source["id"]])
        canonical_before = {str(p.relative_to(self.vault.root)): p.read_bytes() for p in self.vault.root.rglob("*") if p.is_file()}
        destination = self.root / "snapshot with spaces"
        result = self.export(destination, project="atlas")
        notes = self.notes(destination)
        self.assertEqual(result["records"], 2)
        self.assertEqual(result["snapshot"], self.vault.snapshot_id())
        for record in (source, note):
            metadata, body, file = notes[record["id"]]
            self.assertEqual(metadata["revision"], record["revision"])
            self.assertEqual(metadata["title"], record["title"])
            self.assertEqual(metadata["sources"], record["sources"])
            self.assertTrue(file.read_bytes().endswith(record["body"].encode("utf-8")))
            self.assertIn("edits do not update the live vault", body.lower())
        for file in destination.rglob("*.md"):
            markdown = file.read_text(encoding="utf-8")
            if markdown.startswith("---\n"):
                markdown = markdown.split("---\n", 2)[2]
            for link in re.findall(r"\]\(([^)]+)\)", markdown):
                self.assertTrue((file.parent / link).is_file(), (file, link))
        self.assertEqual({str(p.relative_to(self.vault.root)): p.read_bytes() for p in self.vault.root.rglob("*") if p.is_file()}, canonical_before)
        notes[note["id"]][2].write_text("edited export", encoding="utf-8")
        self.assertEqual(self.vault.get(note["id"])["body"], note["body"])

    def test_history_is_opt_in_and_ungranted_predecessor_refs_are_omitted(self):
        old = self.vault.put(title="Old choice", body="hidden-predecessor-body", scope="personal", record_id="hidden-predecessor-id")
        new = self.vault.correct(old["id"], expected_revision=old["revision"], title="Current choice", body="current-body")
        proposed = self.vault.put(title="Unconfirmed", body="proposal-body", scope="personal", state="proposed")
        baseline = self.root / "baseline"
        self.export(baseline, personal=True)
        self.assertEqual(set(self.notes(baseline)), {new["id"]})
        self.assertIsNone(self.notes(baseline)[new["id"]][0]["supersedes"])
        history = self.root / "history"
        self.export(history, personal=True, include_history=True)
        self.assertEqual(set(self.notes(history)), {old["id"], new["id"], proposed["id"]})
        self.assertEqual(self.notes(history)[new["id"]][0]["supersedes"], old["id"])
        self.vault.grant("atlas", new["id"])
        scoped = self.root / "scoped-history"
        self.export(scoped, project="atlas", include_history=True)
        self.assertEqual(set(self.notes(scoped)), {new["id"]})
        self.assertNotIn(old["id"], self.all_text(scoped))
        self.assertNotIn(old["body"], self.all_text(scoped))

    def test_obsolete_source_is_only_exported_with_explicit_history(self):
        old_source = self.vault.put(title="Original reference", body="obsolete-evidence", scope="personal", kind="source")
        old_decision = self.vault.put(title="Original decision", body="obsolete-decision", scope="personal", sources=[old_source["id"]])
        new_source = self.vault.put(title="Current reference", body="current-evidence", scope="personal", kind="source")
        new_decision = self.vault.correct(old_decision["id"], expected_revision=old_decision["revision"], title="Current decision", body="current-decision", sources=[new_source["id"]])
        baseline = self.root / "current-references"
        self.export(baseline, personal=True)
        self.assertEqual(set(self.notes(baseline)), {new_source["id"], new_decision["id"]})
        self.assertNotIn(old_source["id"], self.all_text(baseline))
        self.assertNotIn(old_source["body"], self.all_text(baseline))
        history = self.root / "all-references"
        self.export(history, personal=True, include_history=True)
        self.assertEqual(set(self.notes(history)), {old_source["id"], old_decision["id"], new_source["id"], new_decision["id"]})

    def test_existing_destination_and_canonical_nested_paths_are_preserved(self):
        destination = self.root / "existing"
        destination.mkdir()
        important = destination / "Home.md"
        important.write_bytes(b"user content")
        with self.assertRaises(VaultError):
            self.export(destination, personal=True)
        self.assertEqual(important.read_bytes(), b"user content")
        self.assertEqual(list(destination.iterdir()), [important])
        nested = self.vault.root / "snapshot"
        with self.assertRaises(VaultError):
            self.export(nested, personal=True)
        self.assertFalse(nested.exists())
        existing_file = self.root / "existing-file.md"
        existing_file.write_bytes(b"another user file")
        with self.assertRaises(VaultError):
            self.export(existing_file, personal=True)
        self.assertEqual(existing_file.read_bytes(), b"another user file")

    def test_symlink_ancestor_is_rejected_before_export_writes(self):
        linked = self.root / "linked"
        try:
            os.symlink(self.vault.root, linked, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("This OS account cannot create directory symlinks")
            # Directory junctions do not require Windows symlink privileges.
            created = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(linked), str(self.vault.root)], capture_output=True)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        with self.assertRaises(VaultError):
            self.export(linked / "snapshot", personal=True)
        self.assertFalse((self.vault.root / "snapshot").exists())

    def test_changed_source_during_write_leaves_only_incomplete_snapshot(self):
        self.vault.put(title="Original", body="stable-source", scope="personal")
        destination = self.root / "changed"
        original_snapshot = self.vault.snapshot_id
        changed = False
        def snapshot():
            nonlocal changed
            if destination.exists() and not changed:
                changed = True
                self.vault.put(title="New", body="concurrent-change", scope="personal")
            return original_snapshot()
        with patch.object(self.vault, "snapshot_id", side_effect=snapshot):
            with self.assertRaises(VaultError) as failure:
                self.export(destination, personal=True)
        self.assertEqual(failure.exception.code, "source_changed")
        self.assertTrue((destination / "INCOMPLETE.md").is_file())
        self.assertFalse((destination / "COMPLETE.md").exists())

    def test_external_payload_edit_during_export_fails_without_repairing_source(self):
        record = self.vault.put(title="Source", body="source-evidence", scope="personal", kind="source")
        payload = self.vault.root / record["path"]
        destination = self.root / "externally-changed"
        original_snapshot = self.vault.snapshot_id
        changed = False
        def snapshot():
            nonlocal changed
            if destination.exists() and not changed:
                changed = True
                payload.write_bytes(b"externally edited human content")
            return original_snapshot()
        with patch.object(self.vault, "snapshot_id", side_effect=snapshot):
            with self.assertRaises(VaultError) as failure:
                self.export(destination, personal=True)
        self.assertEqual(failure.exception.code, "source_changed")
        self.assertEqual(payload.read_bytes(), b"externally edited human content")
        self.assertTrue((destination / "INCOMPLETE.md").is_file())
        self.assertFalse((destination / "COMPLETE.md").exists())

    def test_modified_incomplete_marker_is_preserved_instead_of_deleted(self):
        destination = self.root / "marker-edited"
        original_snapshot = self.vault.snapshot_id
        changed = False
        def snapshot():
            nonlocal changed
            marker = destination / "INCOMPLETE.md"
            if marker.exists() and not changed:
                changed = True
                marker.write_bytes(b"owner added content to this marker")
            return original_snapshot()
        with patch.object(self.vault, "snapshot_id", side_effect=snapshot):
            with self.assertRaises(VaultError):
                self.export(destination, personal=True)
        self.assertEqual((destination / "INCOMPLETE.md").read_bytes(), b"owner added content to this marker")

    def test_revocation_in_last_path_guard_is_rechecked_before_completion(self):
        from remember_dammit import exporting
        record = self.vault.put(title="Granted choice", body="revoked-before-completion", scope="personal")
        self.vault.grant("atlas", record["id"])
        destination = self.root / "last-guard-revoke"
        original_guard = exporting._guard
        revoked = False
        def guard(*args, **kwargs):
            nonlocal revoked
            original_guard(*args, **kwargs)
            if (destination / "COMPLETE.md").exists() and not revoked:
                revoked = True
                self.vault.revoke("atlas", record["id"])
        with patch.object(exporting, "_guard", side_effect=guard):
            with self.assertRaises(VaultError) as failure:
                self.export(destination, project="atlas")
        self.assertEqual(failure.exception.code, "source_changed")
        self.assertTrue((destination / "INCOMPLETE.md").is_file())
        self.assertNotIn(record["id"], self.vault.grants_for("atlas"))

    def test_actual_revoker_waits_until_completion_marker_removal(self):
        record = self.vault.put(title="Granted choice", body="valid-at-publication", scope="personal")
        self.vault.grant("atlas", record["id"])
        initial_snapshot = self.vault.snapshot_id()
        destination = self.root / "serialized-finalization"
        marker = destination / "INCOMPLETE.md"
        original_unlink = Path.unlink
        started = threading.Event()
        committed = threading.Event()
        failures = []
        observed_before_removal = []
        def revoke():
            started.set()
            try:
                Vault(self.vault.root).revoke("atlas", record["id"])
                committed.set()
            except Exception as error:
                failures.append(error)
        revoker = threading.Thread(target=revoke, daemon=True)
        def unlink(path, *args, **kwargs):
            if path == marker:
                revoker.start()
                self.assertTrue(started.wait(3), "The real revoker thread did not start")
                observed_before_removal.append(committed.wait(0.3))
            return original_unlink(path, *args, **kwargs)
        try:
            with patch.object(Path, "unlink", unlink):
                result = self.export(destination, project="atlas")
        finally:
            if revoker.ident is not None:
                revoker.join(timeout=5)
        self.assertFalse(revoker.is_alive(), "The cooperating writer stayed blocked after finalization")
        self.assertEqual(failures, [])
        self.assertTrue(committed.is_set(), "The real revocation did not commit after finalization")
        self.assertEqual(observed_before_removal, [False], "Revocation committed before the export's completion point")
        self.assertEqual(result["snapshot"], initial_snapshot)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(marker.exists())
        self.assertNotIn(record["id"], self.vault.grants_for("atlas"))

    def test_invalid_selections_fail_without_creating_output(self):
        for number, selection in enumerate(({}, {"project": "atlas", "personal": True}, {"project": "../bad"}, {"personal": "yes"}, {"personal": True, "include_history": "yes"})):
            destination = self.root / f"invalid-{number}"
            with self.subTest(selection=selection), self.assertRaises(VaultError):
                self.export(destination, **selection)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
