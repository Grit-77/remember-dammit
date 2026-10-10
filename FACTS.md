# Publication facts

Implementation reviewed: `9cc5b7e` — source alpha 0.1.0a4, 2026-10-10. Initial core reviewed at `c8e4b2c`; Markdown import reviewed at `e429bb3` plus `2aacc9e`; workspace setup at `1a58324`; diagnostics and optional shadow assessment at `e3830bc`. Vault navigation and authoring are covered by the checks below; consult per-commit CI for the published tree. Run commands from this checkout in an environment installed with `python -m pip install -e ".[mcp]"`.

| Public statement | Receipt | Scope and limits |
| --- | --- | --- |
| Local Markdown records, corrections, grants and history | `python -m unittest discover -s tests -p test_storage.py -v`; `src/remember_dammit/storage.py` | Real temporary vaults and participating-process operations; not a freely editable Obsidian workspace. |
| Scoped queryless overview, task/proposal counts and source backlinks | `python -m unittest discover -s tests -p test_overview.py -v`; `test_mcp.py`; `test_cli_vault.py` | Exact structured source links, active/proposed selection and omission counts. No semantic linking, task-completion inference or universal byte-budget claim. |
| Markdown title/body editing through reviewed working copies | `python -m unittest discover -s tests -p test_editing.py -v`; `test_cli_vault.py`; `src/remember_dammit/editing.py` | Temporary vault roundtrip, immutable predecessors, stale-head conflicts, policy checks, untrusted metadata, exact receipts and partial recovery; no automatic workspace refresh or text merge. |
| Atomic snapshot precondition for a new correction | `python -m unittest discover -s tests -p 'test_storage*.py' -v`; `Vault.correct` | Snapshot checked inside the writer lock; exact operation replay still acknowledges its historical result. This does not make a multi-record batch atomic. |
| Scoped lexical passages, corrections, citations and byte-budgeted packets | `python -m unittest discover -s tests -p test_retrieval.py -v`; `test_workflow.py` | Lexical fixtures, explicit scopes, selected source dependencies; not universal semantic recall. |
| CLI and local stdio MCP share the core | `python -m unittest discover -s tests -p test_cli.py -v`; `test_mcp.py` | Real CLI and SDK subprocesses, not native model/IDE acceptance. |
| Four client configuration proposals | `python -m unittest discover -s tests -p test_integrations.py -v`; `src/remember_dammit/integrations.py` | Parsed JSON/TOML, literal argument handling and emitted-command launches. Each proposal says `tested_live: false`. |
| New-directory scoped Markdown snapshot export | `python -m unittest discover -s tests -p test_exporting.py -v`; `test_cli_export.py` | Source filtering, existing-file preservation and participating-writer finalization; exports do not write back. |
| Workspace setup preserves existing settings | `python -m unittest discover -s tests -p test_setup.py -v`; `test_cli_setup.py`; `src/remember_dammit/setup.py` | Temporary files, dry run, conflicts, repeat setup and injected failures. Not native-client acceptance; backups stay outside workspace/vault. |
| Packaged first-use interview and optional advisor choice | `src/remember_dammit/templates/remember-dammit/SKILL.md`; `docs/AGENT-SETUP.md`; `test_integrations.py` | Instruction and package-resource checks plus disposable SDK save/readback. No claim that every model follows the skill; selection does not activate a provider. |
| Read-only workspace installation diagnosis | `python -m unittest discover -s tests -p '*diagnostics.py' -v`; `src/remember_dammit/diagnostics.py` | Configuration, skill, runtime and vault fixtures; local readiness does not establish native client approval. |
| Explicit Jev/Laya shadow protocol adapters | `python -m unittest discover -s tests -p '*advisors.py' -v`; `src/remember_dammit/advisors.py` | Synthetic protocol and loopback HTTP fixtures, no paid inference or model download; no live readiness or judgment-quality claim. |
| Advisor off/preview, remote query gate and dependency filtering | `tests/test_advisors.py`; `docs/PROVIDERS.md` | Off and preview do not read credentials or send requests; explicit assessment remains separate from baseline recall and cannot write canonical memory. |
| Provider setup examples | Official TypeSafe OpenAPI/models and pinned Laya server/package references linked in `docs/PROVIDERS.md`, inspected 2026-10-10 | Commands derive from primary provider contracts; new provider installation and live inference were not executed. |
| Read-only source-folder import with preview and retry | `python -m unittest discover -s tests -p '*import*.py' -v`; `src/remember_dammit/importing.py` | Explicit plan, source hashes, preserved originals, stable IDs, corrections and reported partial batches; not live editor sync. |
| Provider-free core demo | `python -m unittest discover -s tests -p test_demo.py -v`; `examples/demo.py` | Real synthetic persistence, correction and reopened recall. No native AI client is invoked. |
| No model API key or provider invocation in the core path | `storage.py`, `retrieval.py`, `mcp_server.py` and the core demo; `pyproject.toml` separates the MCP extra | The connected AI client still uses its normal account/provider. Explicit configured `assess` is a separate optional path. |
| Core-only wheel installation works | `python -m pip wheel --no-deps .`; install that wheel into a clean virtual environment, run `examples/demo.py` using that interpreter | Observed locally with Python 3.12.14 and PyYAML 6.0.3, without the MCP package in the clean environment. |
| Tests and platform observations | `python -m unittest discover -s tests -v`; per-commit [CI results](https://github.com/Grit-77/remember-dammit/actions/workflows/test.yml) | Native four-harness behavior is a separate, still-open acceptance matrix. |
| Apache-2.0 license | `LICENSE`, `NOTICE`, `pyproject.toml`; owner decision 2026-10-10 | Applies to this publication revision; previous commits retain their recorded license text. |

The repository's detailed architecture documents are proposals. Their planned capabilities must not be presented as shipped behavior; [STATUS.md](docs/STATUS.md) enumerates current boundaries.

## Publication copy changes

- Removed the obsolete “no public remote” statement once publication was authorized.
- Corrected the illustrative vault's statement that IDs/revision manifests had not been implemented; the example remains non-executable.
- Recorded the current Python packaging and license choice instead of calling them undecided.
- Linked CI rather than implying a configured matrix had already passed.
- Labeled the broader propose/commit/reconciliation protocol as a target, separate from the current tool surface.
- No star, performance, token-saving, perfect-recall or native four-client success figure is claimed.
- Removed third-party project comparisons, inspiration acknowledgements, and external documentation citations from the product narrative at the owner's request. Harness names remain where needed for compatibility and installation.
- Switched the current publication's license metadata and license text to Apache-2.0 after explicit owner approval; added NOTICE.

- Added workspace setup, the packaged interview/readback skill, and explicit pending advisor choices at `1a58324`; commands are covered by setup and CLI tests.
- Added reviewed Markdown import at `cab0fc0` and `ac11b02`; removed its previous unimplemented label while retaining the editor-sync limit.
- Added read-only setup diagnostics and opt-in shadow advisor adapters; replaced the unavailable-connector label with the actual CLI scope and retained live-provider verification limits.
- Added scoped navigation and explicit working-note corrections. Kept canonical revisions immutable, preserved source/grant identity semantics and documented the new-folder-per-editing-round limit.
