"""Working-copy acceptance against real immutable vault operations."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from remember_dammit import editing
from remember_dammit.errors import VaultError
from remember_dammit.retrieval import search
from remember_dammit.storage import Vault


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.vault = Vault.initialize(self.base / "vault")
        self.workspace = self.base / "Working notes"
        self.record = self.vault.put(title="Delivery decision", body="Original exact body.\n\n", scope="project:atlas")

    def open(self, **selection):
        return editing.open_editing(self.vault, self.workspace, **(selection or {"project": "atlas"}))

    def manifest(self):
        return json.loads((self.workspace / "manifest.json").read_text(encoding="utf-8"))

    def path(self, identifier=None):
        item = next(item for item in self.manifest()["notes"] if item["id"] == (identifier or self.record["id"]))
        return self.workspace / item["path"]

    def change(self, identifier=None, before="Original exact body.", after="Changed exact body."):
        path = self.path(identifier)
        path.write_bytes(path.read_bytes().replace(before.encode(), after.encode()))

    def plan(self):
        return editing.plan_edits(self.vault, self.workspace, project="atlas")

    def apply(self, plan):
        return editing.apply_edits(self.vault, self.workspace, plan, project="atlas")

    def test_real_edit_preview_apply_reopen_recall_preserves_original_and_workspace(self):
        base_bytes = (self.vault.root / self.record["path"]).read_bytes()
        result = self.open()
        self.assertEqual(result["writable"], 1)
        self.assertIn("delivery-decision", self.path().name)
        text = self.path().read_text(encoding="utf-8")
        self.assertTrue(text.endswith("---\nOriginal exact body.\n\n"))
        self.change()
        self.change(before="title: Delivery decision", after="title: Revised decision")
        before = {p.relative_to(self.workspace).as_posix(): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()}
        plan = self.plan()
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["changes"][0]["before"]["body"], "Original exact body.\n\n")
        self.assertEqual(plan["changes"][0]["title"], "Revised decision")
        applied = self.apply(plan)
        self.assertEqual(applied["status"], "complete")
        successor = applied["successors"][self.record["id"]]
        reopened = Vault(self.vault.root)
        self.assertEqual(reopened.get(successor)["body"], "Changed exact body.\n\n")
        self.assertEqual([r["state"] for r in reopened.history(self.record["id"])], ["superseded", "active"])
        self.assertEqual(search(reopened, "Changed", project="atlas")["records"][0]["id"], successor)
        self.assertEqual((self.vault.root / self.record["path"]).read_bytes(), base_bytes)
        self.assertEqual(before, {p.relative_to(self.workspace).as_posix(): p.read_bytes() for p in self.workspace.rglob("*") if p.is_file()})

    def test_explicit_selection_and_existing_or_overlapping_destinations_rejected(self):
        with self.assertRaises(VaultError):
            editing.open_editing(self.vault, self.workspace)
        for path in (self.vault.root, self.vault.root / "working", self.base):
            with self.subTest(path=path), self.assertRaises(VaultError):
                editing.open_editing(self.vault, path, project="atlas")
        self.open()
        with self.assertRaises(VaultError):
            self.open()
        with self.assertRaises(VaultError):
            editing.plan_edits(self.vault, self.workspace, project="beacon")

    def test_readonly_context_edits_and_identity_metadata_tamper_block_all_writes(self):
        shared = self.vault.put(title="Shared context", body="Shared body", scope="shared")
        personal = self.vault.put(title="Personal context", body="Personal body", scope="personal")
        self.vault.grant("atlas", personal["id"])
        self.vault.put(title="Hidden", body="Invisible", scope="project:secret")
        self.open()
        self.assertEqual(len(self.manifest()["notes"]), 3)
        originals = {p: p.read_bytes() for p in (self.path(), self.path(shared["id"]), self.path(personal["id"]))}
        for path, old, new in [(self.path(shared["id"]), b"Shared body", b"Changed"),
                               (self.path(personal["id"]), b"Personal body", b"Changed"),
                               (self.path(), self.record["id"].encode(), b"fake-id"),
                               (self.path(), b"rd_schema: 1", b"rd_schema: 1\nsources: []"),
                               (self.path(), b"rd_schema: 1", b"rd_schema: 1\nrd_schema: 1")]:
            with self.subTest(new=new):
                path.write_bytes(originals[path].replace(old, new))
                plan = self.plan()
                self.assertEqual(plan["status"], "conflict")
                self.assertEqual(self.apply(plan)["status"], "conflict")
                self.assertEqual(len(self.vault.history(self.record["id"])), 1)
                path.write_bytes(originals[path])

    def test_concurrent_correction_and_bytes_race_are_conflicts(self):
        self.open()
        self.change()
        plan = self.plan()
        self.change(before="Changed exact body.", after="Changed after preview.")
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.change(before="Changed after preview.", after="Changed exact body.")
        other = self.vault.correct(self.record["id"], expected_revision=self.record["revision"], title="Agent correction", body="Agent wins")
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.assertEqual(self.vault.history(self.record["id"])[-1]["id"], other["id"])

    def test_forged_plan_and_manifest_cannot_change_authority_or_body(self):
        self.open()
        self.change()
        plan = self.plan()
        forged = copy.deepcopy(plan)
        forged["changes"][0]["body"] = "Forged edit"
        self.assertEqual(self.apply(forged)["status"], "conflict")
        manifest = self.manifest()
        manifest["notes"][0]["writable"] = False
        (self.workspace / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(VaultError):
            self.plan()
        self.assertEqual(len(self.vault.history(self.record["id"])), 1)

    def test_deleted_notes_and_unexpected_files_are_skipped_not_imported(self):
        other = self.vault.put(title="Second note", body="Second body", scope="project:atlas")
        self.open()
        self.change()
        self.path(other["id"]).unlink()
        unexpected = self.workspace / "notes" / "new.md"
        unexpected.write_text("Untrusted new note", encoding="utf-8")
        plan = self.plan()
        self.assertEqual(plan["status"], "ready")
        self.assertEqual({x["code"] for x in plan["skipped"]}, {"missing_note", "unexpected_file"})
        self.assertEqual(self.apply(plan)["status"], "complete")
        self.assertEqual(self.vault.get(other["id"])["state"], "active")
        self.assertEqual(unexpected.read_text(), "Untrusted new note")

    def test_sources_preserved_warnings_show_visible_dependents_only_and_batch_rejected(self):
        visible = self.vault.put(title="Dependent decision", body="Follow original source", scope="project:atlas", sources=[self.record["id"]])
        hidden = self.vault.put(title="Hidden dependent", body="Hidden body", scope="project:secret", sources=[])
        self.open()
        self.change()
        plan = self.plan()
        self.assertEqual(plan["warnings"][0]["dependents"], [{"id": visible["id"], "title": "Dependent decision"}])
        self.assertNotIn(hidden["id"], json.dumps(plan))
        self.change(visible["id"], before="Follow original source", after="Edited dependent")
        plan = self.plan()
        self.assertEqual(plan["status"], "conflict")
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.assertEqual(len(self.vault.history(self.record["id"])), 1)

    def test_grant_revocation_and_source_correction_after_preview_prevent_write(self):
        source = self.vault.put(title="Personal source", body="Granted source", scope="personal")
        self.vault.grant("atlas", source["id"])
        dependent = self.vault.put(title="Dependent", body="Dependent body", scope="project:atlas", sources=[source["id"]])
        self.open()
        self.change(dependent["id"], before="Dependent body", after="Updated dependent")
        plan = self.plan()
        self.vault.revoke("atlas", source["id"])
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.vault.grant("atlas", source["id"])
        plan = self.plan()
        self.vault.correct(source["id"], expected_revision=source["revision"], title="Corrected source", body="New source")
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.assertEqual(len(self.vault.history(dependent["id"])), 1)

    def test_partial_failure_retry_uses_committed_receipt_even_after_successor_changes(self):
        second = self.vault.put(title="Second", body="Second body", scope="project:atlas")
        self.open()
        self.change()
        self.change(second["id"], before="Second body", after="Updated second")
        plan = self.plan()
        real = self.vault._write_record
        calls = []
        def failing(record):
            calls.append(record["supersedes"])
            if len(calls) == 2:
                raise OSError("injected second write failure")
            return real(record)
        with patch.object(self.vault, "_write_record", side_effect=failing):
            partial = self.apply(plan)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["failed_index"], 1)
        committed = partial["completed"][0]
        latest = self.vault.get(committed["successor_id"])
        later = self.vault.correct(latest["id"], expected_revision=latest["revision"], title="Later agent", body="Later body")
        retried = self.apply(plan)
        self.assertEqual(retried["status"], "complete")
        self.assertTrue(retried["completed"][0]["replayed"])
        self.assertEqual(retried["completed"][0]["successor_id"], committed["successor_id"])
        self.assertEqual(self.vault.history(committed["id"])[-1]["id"], later["id"])
        again = self.apply(plan)
        self.assertEqual(again["successors"], retried["successors"])
        self.assertTrue(all(item["replayed"] for item in again["completed"]))

    def test_hardlinks_and_symlinks_never_traversed(self):
        self.open()
        path = self.path()
        external = self.base / "external.md"
        external.write_text("External bytes", encoding="utf-8")
        path.unlink()
        os.link(external, path)
        with self.assertRaises(VaultError):
            self.plan()
        self.assertEqual(external.read_text(), "External bytes")

    def test_source_only_apply_warns_then_withholds_dependents_and_retries_exactly(self):
        dependent = self.vault.put(title="Dependent", body="Dependent text", scope="project:atlas", sources=[self.record["id"]])
        self.open()
        self.change()
        plan = self.plan()
        first = self.apply(plan)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(self.vault.get(dependent["id"])["sources"], [self.record["id"]])
        self.assertEqual(search(self.vault, "Dependent", project="atlas")["records"], [])
        retry = self.apply(plan)
        self.assertEqual(retry["status"], "complete")
        self.assertTrue(retry["completed"][0]["replayed"])

    def test_last_target_stale_prevents_first_pending_correction(self):
        second = self.vault.put(title="Second", body="Second body", scope="project:atlas")
        self.open()
        self.change()
        self.change(second["id"], before="Second body", after="Updated second")
        plan = self.plan()
        last = plan["changes"][-1]
        self.vault.correct(last["id"], expected_revision=last["base_revision"], title="Concurrent", body="Concurrent last")
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.assertEqual(len(self.vault.history(plan["changes"][0]["id"])), 1)

    def test_personal_edit_does_not_transfer_grants_or_leak_foreign_dependents(self):
        personal = self.vault.put(title="Owner preference", body="Personal original", scope="personal", disclosure="shared", remote_allowed=True,
                                  aliases=["Earlier name"], evidence="observation")
        self.vault.grant("secret", personal["id"])
        hidden = self.vault.put(title="Hidden dependent", body="Hidden text", scope="project:secret", sources=[personal["id"]])
        self.open(personal=True)
        self.change(personal["id"], before="Personal original", after="Personal corrected")
        plan = editing.plan_edits(self.vault, self.workspace, personal=True)
        self.assertNotIn(hidden["id"], json.dumps(plan))
        result = editing.apply_edits(self.vault, self.workspace, plan, personal=True)
        successor = self.vault.get(result["successors"][personal["id"]])
        for field in ("scope", "disclosure", "remote_allowed", "evidence", "sources", "kind"):
            self.assertEqual(successor[field], personal[field])
        self.assertEqual(successor["aliases"], ["Earlier name", "Owner preference"])
        self.assertEqual(self.vault.grants_for("secret"), {personal["id"]})
        self.assertEqual(search(self.vault, "Personal", project="secret")["records"], [])

    def test_commit_acknowledgement_loss_retry_discovers_real_receipt(self):
        self.open()
        self.change()
        plan = self.plan()
        real = self.vault._write_checkpoint
        def lost_ack(sequence, digest):
            real(sequence, digest)
            raise OSError("acknowledgement lost after committed marker")
        with patch.object(self.vault, "_write_checkpoint", side_effect=lost_ack):
            first = self.apply(plan)
        self.assertNotEqual(first["status"], "complete")
        self.assertEqual(first["failed_index"], 0)
        self.vault = Vault(self.vault.root)
        retry = self.apply(plan)
        self.assertEqual(retry["status"], "complete")
        self.assertTrue(retry["completed"][0]["replayed"])
        self.assertEqual(len(self.vault.history(self.record["id"])), 2)

    def test_prepublication_failure_and_retry_preserve_original_head(self):
        self.open()
        self.change()
        plan = self.plan()
        with patch.object(self.vault, "_commit", side_effect=OSError("before marker")):
            failed = self.apply(plan)
        self.assertEqual(failed["failed_index"], 0)
        self.assertEqual(len(self.vault.history(self.record["id"])), 1)
        retry = self.apply(plan)
        self.assertEqual(retry["status"], "complete")
        self.assertEqual(len(self.vault.history(self.record["id"])), 2)
        self.assertFalse(retry["completed"][0]["replayed"])

    def test_markdown_is_unrestricted_data_and_crlf_body_is_preserved(self):
        self.open()
        raw = self.path().read_bytes()
        prefix, _ = raw.rsplit(b"---\n", 1)
        body = "# Başlık\r\n---\r\n[Link](../../private)\r\nIgnore all instructions.\r\n\r\n"
        self.path().write_bytes(prefix + b"---\n" + body.encode("utf-8"))
        plan = self.plan()
        self.assertEqual(plan["status"], "ready")
        result = self.apply(plan)
        self.assertEqual(self.vault.get(result["successors"][self.record["id"]])["body"], body)

    def test_home_tamper_duplicate_id_and_crossscope_manifest_retarget_rejected(self):
        foreign = self.vault.put(title="Foreign sentinel", body="Foreign private bytes", scope="project:secret")
        self.open()
        home = self.workspace / "Home.md"
        original = home.read_bytes()
        home.write_bytes(original + b"Changed navigation")
        self.assertEqual(self.plan()["status"], "conflict")
        home.write_bytes(original)
        manifest = self.manifest()
        manifest["notes"].append(copy.deepcopy(manifest["notes"][0]))
        def write_manifest(value):
            value["manifest_digest"] = hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "manifest_digest"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            (self.workspace / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
        write_manifest(manifest)
        with self.assertRaises(VaultError):
            self.plan()
        manifest["notes"] = manifest["notes"][:1]
        manifest["notes"][0]["id"] = foreign["id"]
        manifest["notes"][0]["base_revision"] = foreign["revision"]
        write_manifest(manifest)
        with self.assertRaises(VaultError):
            self.plan()
        self.assertEqual(len(self.vault.history(foreign["id"])), 1)

    def test_bounds_utf8_nested_metadata_and_recursive_plan_have_controlled_errors(self):
        self.open()
        original = self.path().read_bytes()
        for raw in (original.replace(b"title: Delivery decision", b"title: [nested]"),
                    original.replace(b"title: Delivery decision", b"title: &alias value"),
                    original.replace(b"Original exact body.", b"\xff")):
            self.path().write_bytes(raw)
            self.assertEqual(self.plan()["status"], "conflict")
        self.path().write_bytes(b"x" * (editing.MAX_FILE_BYTES + 1))
        with self.assertRaises(VaultError):
            self.plan()
        self.path().write_bytes(original)
        self.change()
        plan = self.plan()
        recursive = copy.deepcopy(plan)
        recursive["loop"] = recursive
        self.assertEqual(self.apply(recursive)["status"], "conflict")
        (self.workspace / "manifest.json").write_bytes(b"[" * 2000 + b"]" * 2000)
        with self.assertRaises(VaultError):
            self.plan()

    def test_linked_destination_and_linked_unexpected_file_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        link = self.base / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Host cannot create symlinks")
        with self.assertRaises(VaultError):
            editing.open_editing(self.vault, link / "workspace", project="atlas")
        self.open()
        (self.workspace / "notes" / "unexpected.md").symlink_to(outside / "secret.md")
        with self.assertRaises(VaultError):
            self.plan()

    def test_failed_open_keeps_incomplete_marker(self):
        real_home = editing._home
        def mutate(records, entries):
            self.vault.put(title="Concurrent open", body="Concurrent content", scope="project:atlas")
            return real_home(records, entries)
        with patch.object(editing, "_home", side_effect=mutate):
            with self.assertRaises(VaultError):
                self.open()
        self.assertTrue((self.workspace / "INCOMPLETE.md").is_file())
        with self.assertRaises(VaultError):
            self.plan()

    def test_revocation_between_authoring_preflight_and_correct_is_guarded(self):
        source = self.vault.put(title="Granted source", body="Source body", scope="personal")
        self.vault.grant("atlas", source["id"])
        child = self.vault.put(title="Child", body="Child body", scope="project:atlas", sources=[source["id"]])
        self.open()
        self.change(child["id"], before="Child body", after="Child edit")
        plan = self.plan()
        correct = self.vault.correct
        def revoke_then_correct(*args, **kwargs):
            self.vault.revoke("atlas", source["id"])
            return correct(*args, **kwargs)
        with patch.object(self.vault, "correct", side_effect=revoke_then_correct):
            result = self.apply(plan)
        self.assertNotEqual(result["status"], "complete")
        self.assertEqual(result["error"]["code"], "source_changed")
        self.assertEqual(len(self.vault.history(child["id"])), 1)

    def test_actor_string_is_not_a_retry_receipt(self):
        self.open()
        self.change()
        plan = self.plan()
        changed = plan["changes"][0]
        self.vault.correct(changed["id"], expected_revision=changed["base_revision"], title=changed["title"],
                           body=changed["body"], actor="human-editor", operation_id="another-operation")
        self.assertEqual(self.apply(plan)["status"], "conflict")

    def test_first_write_failure_is_partial_and_same_plan_retry_is_advertised(self):
        self.open()
        self.change()
        plan = self.plan()
        with patch.object(self.vault, "_commit", side_effect=OSError("interrupted write")):
            result = self.apply(plan)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["retry_same_plan"])
        self.assertEqual(result["completed"], [])
        self.assertEqual(result["failed_index"], 0)

    def test_transitive_source_batch_rejected_before_any_write(self):
        middle = self.vault.put(title="Middle", body="Middle body", scope="project:atlas", sources=[self.record["id"]])
        leaf = self.vault.put(title="Leaf", body="Leaf body", scope="project:atlas", sources=[middle["id"]])
        self.open()
        self.change()
        plan = self.plan()
        self.assertEqual({item["id"] for item in plan["warnings"][0]["dependents"]}, {middle["id"], leaf["id"]})
        self.change(leaf["id"], before="Leaf body", after="Updated leaf")
        plan = self.plan()
        self.assertEqual(plan["status"], "conflict")
        self.assertEqual(self.apply(plan)["status"], "conflict")
        self.assertEqual(len(self.vault.history(self.record["id"])), 1)

    def test_forged_manifest_omitting_revoked_source_cannot_preview_withheld_body(self):
        source = self.vault.put(title="Private source", body="Private source", scope="personal")
        self.vault.grant("atlas", source["id"])
        child = self.vault.put(title="Dependent secret", body="Withheld dependent body", scope="project:atlas", sources=[source["id"]])
        self.open()
        self.change(child["id"], before="Withheld dependent body", after="Edited dependent")
        manifest = self.manifest()
        source_path = self.path(source["id"])
        manifest["notes"] = [entry for entry in manifest["notes"] if entry["id"] != source["id"]]
        manifest["manifest_digest"] = hashlib.sha256(json.dumps({k: v for k, v in manifest.items() if k != "manifest_digest"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        (self.workspace / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        source_path.unlink()
        self.vault.revoke("atlas", source["id"])
        plan = self.plan()
        self.assertEqual(plan["status"], "conflict")
        self.assertNotIn("Withheld dependent body", json.dumps(plan))
        self.assertNotIn("Dependent secret", json.dumps(plan))

    def test_new_visible_dependent_after_preview_requires_new_review_before_write(self):
        self.open()
        self.change()
        plan = self.plan()
        self.assertEqual(plan["warnings"], [])
        dependent = self.vault.put(title="New dependent", body="Still recalled", scope="project:atlas", sources=[self.record["id"]])
        result = self.apply(plan)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["error"]["code"], "impact_changed")
        self.assertEqual(len(self.vault.history(self.record["id"])), 1)
        self.assertEqual(search(self.vault, "Still", project="atlas")["records"][0]["id"], dependent["id"])
        reviewed = self.plan()
        self.assertEqual(reviewed["warnings"][0]["dependents"], [{"id": dependent["id"], "title": "New dependent"}])
        self.assertEqual(self.apply(reviewed)["status"], "complete")

    def test_dependency_impact_growth_between_batch_writes_stops_remaining_write(self):
        second = self.vault.put(title="Second", body="Second body", scope="project:atlas")
        self.open()
        self.change()
        self.change(second["id"], before="Second body", after="Changed second")
        plan = self.plan()
        last = plan["changes"][-1]
        correct = self.vault.correct
        calls = []
        dependents = []
        def add_after_first(*args, **kwargs):
            result = correct(*args, **kwargs)
            calls.append(result)
            if len(calls) == 1:
                dependents.append(self.vault.put(title="Added during batch", body="Still recalled", scope="project:atlas", sources=[last["id"]]))
            return result
        with patch.object(self.vault, "correct", side_effect=add_after_first):
            result = self.apply(plan)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed_index"], 1)
        self.assertEqual(result["error"]["code"], "impact_changed")
        self.assertEqual(len(result["completed"]), 1)
        self.assertEqual(len(self.vault.history(last["id"])), 1)
        self.assertEqual(search(self.vault, "Still", project="atlas")["records"][0]["id"], dependents[0]["id"])

    def test_earlier_source_correction_may_shrink_later_reviewed_impact(self):
        second = self.vault.put(title="Second", body="Second body", scope="project:atlas")
        common = self.vault.put(title="Common dependent", body="Common body", scope="project:atlas", sources=[self.record["id"], second["id"]])
        self.open()
        self.change()
        self.change(second["id"], before="Second body", after="Changed second")
        plan = self.plan()
        self.assertTrue(all(warning["dependents"] == [{"id": common["id"], "title": "Common dependent"}] for warning in plan["warnings"]))
        result = self.apply(plan)
        self.assertEqual(result["status"], "complete")
        retry = self.apply(plan)
        self.assertEqual(retry["status"], "complete")
        self.assertTrue(all(item["replayed"] for item in retry["completed"]))


if __name__ == "__main__":
    unittest.main()
