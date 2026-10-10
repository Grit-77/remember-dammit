# Publication facts

Implementation reviewed: `c8e4b2c` (2026-10-10). The initial publication preparation changes documentation only; behavioral receipts below refer to this implementation revision. Run commands from that checkout in an environment installed with `python -m pip install -e ".[mcp]"`.

| Public statement | Receipt | Scope and limits |
| --- | --- | --- |
| Local Markdown records, corrections, grants and history | `python -m unittest discover -s tests -p test_storage.py -v`; `src/remember_dammit/storage.py` | Real temporary vaults and participating-process operations; not a freely editable Obsidian workspace. |
| Scoped lexical passages, corrections, citations and byte-budgeted packets | `python -m unittest discover -s tests -p test_retrieval.py -v`; `test_workflow.py` | Lexical fixtures, explicit scopes, selected source dependencies; not universal semantic recall. |
| CLI and local stdio MCP share the core | `python -m unittest discover -s tests -p test_cli.py -v`; `test_mcp.py` | Real CLI and SDK subprocesses, not native model/IDE acceptance. |
| Four client configuration proposals | `python -m unittest discover -s tests -p test_integrations.py -v`; `src/remember_dammit/integrations.py` | Parsed JSON/TOML, literal argument handling and emitted-command launches. Each proposal says `tested_live: false`. |
| New-directory scoped Markdown snapshot export | `python -m unittest discover -s tests -p test_exporting.py -v`; `test_cli_export.py` | Source filtering, existing-file preservation and participating-writer finalization; exports do not write back. |
| Provider-free core demo | `python -m unittest discover -s tests -p test_demo.py -v`; `examples/demo.py` | Real synthetic persistence, correction and reopened recall. No native AI client is invoked. |
| No model API key or provider invocation in the core path | `storage.py`, `retrieval.py`, `cli.py` and the core demo; `pyproject.toml` separates the MCP extra | The connected AI client still uses its normal account/provider. Optional advisor connectors are unimplemented. |
| Core-only wheel installation works | `python -m pip wheel --no-deps .`; install that wheel into a clean virtual environment, run `examples/demo.py` using that interpreter | Observed locally with Python 3.12.14 and PyYAML 6.0.3, without the MCP package in the clean environment. |
| Tests and platform observations | `python -m unittest discover -s tests -v`; per-commit [CI results](https://github.com/Grit-77/remember-dammit/actions/workflows/test.yml) | Native four-harness behavior is a separate, still-open acceptance matrix. |
| MIT license | `LICENSE`, `pyproject.toml` | Original implementation. Retain applicable upstream notices if code is reused later. |

The repository's detailed architecture documents are proposals. Their planned capabilities must not be presented as shipped behavior; [STATUS.md](docs/STATUS.md) enumerates current boundaries.

## Publication copy changes

- Removed the obsolete “no public remote” statement once publication was authorized.
- Corrected the illustrative vault's statement that IDs/revision manifests had not been implemented; the example remains non-executable.
- Recorded the current Python packaging and MIT choice instead of calling them undecided.
- Linked CI rather than implying a configured matrix had already passed.
- Labeled the broader propose/commit/reconciliation protocol as a target, separate from the current tool surface.
- No star, performance, token-saving, perfect-recall or native four-client success figure is claimed.
