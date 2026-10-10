"""Exercise proposal boundaries without installing client configuration."""

import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from remember_dammit.errors import VaultError


HARNESSES = ("claude", "codex", "cursor", "antigravity")


class IntegrationTests(unittest.TestCase):
    def render(self, *args, **kwargs):
        try:
            module = importlib.import_module("remember_dammit.integrations")
        except ModuleNotFoundError:
            self.fail("The integration proposal renderer is not implemented")
        return module.render(*args, **kwargs)

    def server(self, proposal):
        if proposal["config_format"] == "toml":
            return tomllib.loads(proposal["config_text"])["mcp_servers"]["remember-dammit"]
        self.assertEqual(proposal["config_format"], "json")
        return json.loads(proposal["config_text"])["mcpServers"]["remember-dammit"]

    def test_four_proposals_parse_and_preserve_windows_argv(self):
        vault = 'C:\\Memory vault\\İsmet "notes" & $(echo literal)\\'
        executable = "C:\\Program Files\\Python\\python.exe"
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                proposal = self.render(harness, vault_path=vault, project="demo", python_executable=executable)
                self.assertEqual(set(proposal), {"harness", "config_format", "config_text", "skill_text", "instructions", "tested_live"})
                self.assertEqual(proposal["harness"], harness)
                self.assertIs(proposal["tested_live"], False)
                server = self.server(proposal)
                self.assertEqual(server["command"], executable)
                self.assertEqual(server["args"], ["-m", "remember_dammit", "--vault", vault, "mcp", "--project", "demo"])
                self.assertTrue(proposal["skill_text"].strip())
                self.assertTrue(proposal["instructions"])
                self.assertEqual(set(server), {"command", "args", "type"} if harness == "claude" else {"command", "args"})
                if harness == "claude":
                    self.assertEqual(server["type"], "stdio")

    def test_personal_selection_is_explicit_and_uses_current_interpreter(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                server = self.server(self.render(harness, vault_path="/local/memory", personal=True))
                self.assertEqual(server["command"], sys.executable)
                self.assertEqual(server["args"], ["-m", "remember_dammit", "--vault", "/local/memory", "mcp", "--personal"])

    def test_path_objects_are_serialized_as_paths(self):
        vault = Path("memory vault")
        executable = Path("python executable")
        server = self.server(self.render("codex", vault_path=vault, personal=True, python_executable=executable))
        self.assertEqual(server["command"], "python executable")
        self.assertEqual(server["args"][3], "memory vault")

    def test_missing_conflicting_and_invalid_selections_are_rejected(self):
        for selection in ({}, {"project": "demo", "personal": True}, {"project": ""}, {"project": "   "}, {"project": "--personal"}, {"project": "bad/name"}, {"project": " name "}, {"project": "CON"}, {"project": "demo."}, {"project": "a" * 129}, {"project": 123}, {"personal": "yes"}):
            with self.subTest(selection=selection), self.assertRaises(VaultError):
                self.render("codex", vault_path="/local/memory", **selection)

    def test_unknown_harness_and_invalid_path_values_are_rejected(self):
        for harness in ("other", "CODEX", "", None):
            with self.subTest(harness=harness), self.assertRaises(VaultError):
                self.render(harness, vault_path="/memory", project="demo")
        for field, values in (("vault_path", ("", "   ", "\x00bad", "/vault\nnew", "--personal", 123)), ("python_executable", ("", "\x00python", "python\nnew", 123))):
            for value in values:
                kwargs = {"vault_path": "/memory", "project": "demo", field: value}
                with self.subTest(field=field, value=value), self.assertRaises(VaultError):
                    self.render("codex", **kwargs)

    def test_client_variable_interpolation_is_rejected_in_proposals(self):
        for harness in HARNESSES:
            for field in ("vault_path", "project", "python_executable"):
                kwargs = {"vault_path": "/memory", "project": "demo", "python_executable": "python", field: "${env:HOME}"}
                with self.subTest(harness=harness, field=field), self.assertRaises(VaultError):
                    self.render(harness, **kwargs)

    def test_render_does_not_create_vault_or_change_installed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (".claude.json", ".mcp.json", ".codex/config.toml", ".cursor/mcp.json", ".gemini/config/mcp_config.json", ".agents/mcp_config.json", "AGENTS.md", "CLAUDE.md"):
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("existing settings must survive", encoding="utf-8")
            def snapshot():
                return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            before = snapshot()
            with patch.dict(os.environ, {"HOME": temporary, "USERPROFILE": temporary, "CODEX_HOME": str(root / ".codex")}):
                for harness in HARNESSES:
                    self.render(harness, vault_path=root / "uninitialized vault", project="demo")
            self.assertEqual(snapshot(), before)
            self.assertFalse((root / "uninitialized vault").exists())


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install the optional mcp extra for real emitted-command checks")
class EmittedCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_parsed_proposals_start_real_stdio_server_outside_repository(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        from remember_dammit.integrations import render
        from remember_dammit.storage import Vault

        with tempfile.TemporaryDirectory() as temporary:
            vault = Vault.initialize(Path(temporary) / "Memory vault İ & spaces")
            project_record = vault.put(title="Launch check", body="Project literal path verified", scope="project:demo")
            personal_record = vault.put(title="Owner launch check", body="Personal literal path verified", scope="personal")
            for harness in HARNESSES:
                for selection, visible, hidden in (
                    ({"project": "demo"}, project_record, personal_record),
                    ({"personal": True}, personal_record, project_record),
                ):
                    with self.subTest(harness=harness, selection=selection):
                        proposal = render(harness, vault_path=vault.root, python_executable=sys.executable, **selection)
                        if harness == "codex":
                            server = tomllib.loads(proposal["config_text"])["mcp_servers"]["remember-dammit"]
                        else:
                            server = json.loads(proposal["config_text"])["mcpServers"]["remember-dammit"]
                        parameters = StdioServerParameters(command=server["command"], args=server["args"], cwd=temporary)
                        async with Client(parameters, read_timeout_seconds=15) as client:
                            self.assertIn("show", {tool.name for tool in (await client.list_tools()).tools})
                            result = await client.call_tool("show", {"record_id": visible["id"]})
                            self.assertFalse(result.is_error)
                            record = result.structured_content
                            self.assertIsInstance(record, dict)
                            self.assertEqual(record["id"], visible["id"])
                            self.assertEqual(record["body"], visible["body"])
                            denied = await client.call_tool("show", {"record_id": hidden["id"]})
                            self.assertTrue(denied.is_error)
            self.assertEqual(len(vault.list_records()), 2)


if __name__ == "__main__":
    unittest.main()
