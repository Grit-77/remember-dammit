"""Causal history remains visible through retrieval, imports and navigation."""
import shutil
from pathlib import Path
import tempfile
import unittest

from remember_dammit.errors import VaultError
from remember_dammit.storage import Vault
from remember_dammit import retrieval
from remember_dammit.importing import plan_import, apply_import
from remember_dammit.editing import open_editing, plan_edits
from remember_dammit.overview import overview


def union_into(target, source):
    for path in (source / '.remember').rglob('*'):
        if path.is_file():
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.read_bytes() != path.read_bytes():
                    raise AssertionError('Immutable objects differ')
            else:
                shutil.copyfile(path, destination)


class CausalInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def fork(self, seed):
        left, right = self.root / 'left', self.root / 'right'
        shutil.copytree(seed, left)
        shutil.copytree(seed, right)
        return Vault(left), Vault(right)

    def test_resolved_context_retrieves_terms_from_both_predecessors(self):
        seed = Vault.initialize(self.root / 'seed')
        note = seed.put(title='Delivery choice', body='Original decision.', scope='project:demo')
        left, right = self.fork(seed.root)
        a = left.correct(note['id'], expected_revision=note['revision'], title='Left option', body='Use firstunique.')
        b = right.correct(note['id'], expected_revision=note['revision'], title='Right option', body='Use secondunique.')
        union_into(left.root, right.root)
        heads = [{'id': h['id'], 'revision': h['revision']} for h in left.heads(note['id'])]
        resolved = left.resolve(note['id'], expected_heads=heads, title='Resolved choice', body='Use the reviewed agreement.')
        for query in ('firstunique', 'secondunique'):
            packet = retrieval.context(left, query, project='demo', budget_bytes=6000)
            self.assertEqual([item['id'] for item in packet['records']], [resolved['id']])
            self.assertLessEqual(len(retrieval.encode_packet(packet).encode()), 6000)

    def test_overview_marks_rivals_and_working_notes_require_resolution(self):
        seed = Vault.initialize(self.root / 'seed')
        note = seed.put(title='Decision', body='Original.', scope='project:demo')
        left, right = self.fork(seed.root)
        a = left.correct(note['id'], expected_revision=note['revision'], title='Left', body='Left choice.')
        b = right.correct(note['id'], expected_revision=note['revision'], title='Right', body='Right choice.')
        union_into(left.root, right.root)
        report = overview(left, project='demo')
        self.assertEqual(report['summary']['conflicted_lineages'], 1)
        records = {record['id']: record for record in report['records']}
        self.assertEqual(records[a['id']]['conflicts_with'], [b['id']])
        workspace = self.root / 'working'
        open_editing(left, workspace, project='demo')
        import json
        entry = next(item for item in json.loads((workspace / 'manifest.json').read_bytes())['notes'] if item['id'] == a['id'])
        path = workspace / entry['path']
        path.write_bytes(path.read_bytes().replace(b'Left choice.', b'Edited choice.'))
        plan = plan_edits(left, workspace, project='demo')
        self.assertEqual(plan['status'], 'conflict')
        self.assertIn('competing_heads', {item['code'] for item in plan['conflicts']})

    def test_import_refuses_ambiguous_or_deleted_lineage(self):
        source = self.root / 'notes'
        source.mkdir()
        (source / 'choice.md').write_text('Original choice.', encoding='utf-8')
        seed = Vault.initialize(self.root / 'seed')
        imported = apply_import(seed, plan_import(source, collection='notes', scope='project:demo', vault=seed))
        identifier = imported['completed'][0]['record_id']
        note = seed.get(identifier)
        left, right = self.fork(seed.root)
        left.correct(identifier, expected_revision=note['revision'], title='choice.md', body='Left choice.')
        right.correct(identifier, expected_revision=note['revision'], title='choice.md', body='Right choice.')
        union_into(left.root, right.root)
        with self.assertRaises(VaultError) as raised:
            plan_import(source, collection='notes', scope='project:demo', vault=left)
        self.assertEqual(raised.exception.code, 'import_conflict')
        left.delete(identifier, expected_heads=[{'id': h['id'], 'revision': h['revision']} for h in left.heads(identifier)])
        with self.assertRaises(VaultError):
            plan_import(source, collection='notes', scope='project:demo', vault=left)


if __name__ == '__main__':
    unittest.main()
