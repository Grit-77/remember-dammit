"""Actual SDK stdio clients exercise causal tools, separately from native apps."""
import json
from pathlib import Path
import shutil
import unittest

import test_mcp
from test_causal_interfaces import union_into
from remember_dammit.storage import Vault


@unittest.skipUnless(test_mcp.HAS_MCP, 'Install the optional MCP extra')
class CausalMcpTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_mcp.McpTests.setUp
    client = test_mcp.McpTests.client

    async def test_legacy_mutations_report_migration_required(self):
        self.vault = Vault.initialize(Path(self.temp.name).resolve() / 'legacy', format_version=1)
        record = self.vault.put(title='Legacy decision', body='Keep the original.', scope='project:atlas')
        expected = [{'id': record['id'], 'revision': record['revision']}]
        async with self.client() as client:
            for tool in ('resolve', 'retract'):
                args = {'record_id': record['id'], 'expected_heads': expected}
                if tool == 'resolve':
                    args.update(title='New decision', body='Explicit migration first.')
                result = await client.call_tool(tool, args)
                self.assertTrue(result.is_error)
                self.assertIn('migration_required', str(result.content))

    async def test_retract_receipt_does_not_expose_hidden_root(self):
        self.vault.grant('atlas', self.personal['id'])
        root = self.vault.put(title='Private evidence', body='Old inference.', scope='project:atlas', sources=[self.personal['id']])
        child = self.vault.correct(root['id'], expected_revision=root['revision'], title='Independent evidence', body='New statement.', sources=[])
        self.vault.revoke('atlas', self.personal['id'])
        async with self.client() as client:
            hidden = await client.call_tool('show', {'record_id': root['id']})
            self.assertTrue(hidden.is_error)
            result = await client.call_tool('retract', {'record_id': child['id'], 'expected_heads': [{'id': child['id'], 'revision': child['revision']}]})
            self.assertFalse(result.is_error)
            self.assertTrue(result.structured_content['retracted'])
            self.assertNotIn(root['id'], json.dumps(result.structured_content))

    async def test_stdio_heads_resolution_and_retraction(self):
        base = self.vault.put(title='Decision', body='Original plan.', scope='project:atlas')
        peer_path = Path(self.temp.name).resolve() / 'mac'
        shutil.copytree(self.vault.root, peer_path)
        self.vault.correct(base['id'], expected_revision=base['revision'], title='Windows', body='Use uniquewindows.')
        peer = Vault(peer_path)
        peer.correct(base['id'], expected_revision=base['revision'], title='Mac', body='Use uniquemac.')
        union_into(self.vault.root, peer_path)
        async with self.client() as client:
            response = await client.call_tool('heads', {'record_id': base['id']})
            self.assertFalse(response.is_error)
            heads = response.structured_content['heads']
            self.assertEqual(len(heads), 2)
            expected = [{'id': record['id'], 'revision': record['revision']} for record in heads]
            arguments = {'record_id': base['id'], 'expected_heads': expected, 'title': 'Agreement', 'body': 'Use the chosen plan.'}
            resolved = await client.call_tool('resolve', arguments)
            self.assertFalse(resolved.is_error)
            current = resolved.structured_content
            stale = await client.call_tool('resolve', arguments)
            self.assertTrue(stale.is_error)
            packet = await client.call_tool('context', {'query': 'uniquemac', 'budget_bytes': 5000})
            self.assertFalse(packet.is_error)
            self.assertEqual(packet.structured_content['records'][0]['id'], current['id'])
            retracted = await client.call_tool('retract', {'record_id': current['id'], 'expected_heads': [{'id': current['id'], 'revision': current['revision']}]})
            self.assertFalse(retracted.is_error)
            recalled = await client.call_tool('recall', {'query': 'chosen'})
            self.assertEqual(recalled.structured_content['records'], [])

    async def test_shared_successor_does_not_expose_ungranted_graph_ids(self):
        peer_path = Path(self.temp.name).resolve() / 'mac'
        shutil.copytree(self.vault.root, peer_path)
        one = self.vault.correct(self.personal['id'], expected_revision=self.personal['revision'], title='Shared version', body='This version may be read.')
        other = Vault(peer_path).correct(self.personal['id'], expected_revision=self.personal['revision'], title='Unshared version', body='Keep this private.')
        union_into(self.vault.root, peer_path)
        self.vault.grant('atlas', one['id'])
        async with self.client() as client:
            shown = await client.call_tool('show', {'record_id': one['id']})
        self.assertFalse(shown.is_error)
        text = json.dumps(shown.structured_content)
        self.assertNotIn(self.personal['id'], text)
        self.assertNotIn(other['id'], text)


if __name__ == '__main__':
    unittest.main()
