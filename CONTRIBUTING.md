# Contributing to Remember, Dammit.

Remember, Dammit. is a source alpha. Keep changes small, state what you
observed, and distinguish local library checks from native-client acceptance.

## Set up a development environment

Use Python 3.11 or newer and an isolated virtual environment. From a checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Install the optional MCP dependency only when your change needs the local MCP
server or its tests:

```sh
.venv/bin/python -m pip install -e '.[mcp]'
```

On Windows, create the environment with `python -m venv .venv` and use
`.venv\Scripts\python.exe` in place of `.venv/bin/python`.

## Work safely

Use new, temporary synthetic vaults for development and tests. Do not point
commands at a real agent configuration, personal memory vault, token, local
index, transcript, or customer data. Do not commit any of those materials.

Preserve existing client settings and native permissions. A passing library
test suite does not show that a native client loaded the configuration, received
approval, or accepted a save/recall workflow. See the
[native acceptance report](docs/LIVE-ACCEPTANCE.md) for the observed scope and
its limits.

## Check your change

Run the current complete test suite from the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Also inspect the diff and run any focused check that exercises the changed
behavior. Keep source-alpha limitations intact: native-client behavior and
automatic lifecycle recall require separate acceptance evidence.

## Open a useful pull request

Keep the PR report short and factual:

- changed scope;
- source revision used as the base;
- actual commands and outcomes; and
- remaining uncertainty, including checks not run.

For user-visible or client-integration claims, name the client, platform,
surface, transport, and native trust state that you actually tested. Do not
generalize local tests into native-client acceptance.
