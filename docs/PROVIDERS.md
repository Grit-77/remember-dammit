# Optional Jev and Laya assessment

Local memory works without an advisor, a model download or a provider key. The optional `assess` command can ask Jev or a local Laya server whether each eligible recalled passage is relevant to a query. **Shadow mode reports advice separately: it does not reorder recall, edit memory, approve a write or prove that a statement is true.** Normal CLI recall/context and the MCP server remain provider-free.

## Choose after installation

Ask the user once, in their language: **continue without an advisor, use Jev, or use Laya?** A default `none` in setup is not an answer. Explain the chosen path and check missing prerequisites before helping configure it.

| Choice | What it needs | What setup does |
| --- | --- | --- |
| None | The existing local memory installation | Keep working with recall, save, correction and readback. |
| Jev | A TypeSafe account/key and an explicitly selected hosted model; remote requests may incur provider charges | Explain remote disclosure and billing, create a disabled configuration template, then preview an approved query. |
| Laya | A separately installed compatible server on the same machine; model weights and suitable hardware | Help inspect or provision the chosen server, create a disabled configuration template, then preview a local request. |

For Jev/Laya, setup records the choice and reports the connector as available but `enabled=false`, `setup_status="not_configured"`. It does not create credentials, activate billing, install model weights or configure an MCP provider tool. The operator must deliberately configure and invoke the owner CLI below.

## Create configuration outside the vault

Use the interpreter where Remember, Dammit. is installed. These PowerShell examples print JSON; save it as UTF-8 without a BOM outside the vault and version control, for example under your machine-local configuration directory. Keep the path private. Only the environment-variable **name**, never a key value, belongs in configuration.

```powershell
.venv/Scripts/python.exe -m remember_dammit advisor-template jev --model jev-1.13.0
.venv/Scripts/python.exe -m remember_dammit advisor-template laya --model multilingual
```

Both templates start in `mode="off"`. Set `mode="shadow"` in the reviewed file when the user chooses to use it, or explicitly pass `--mode shadow` when generating the template. Modes other than off/shadow are unsupported. A missing configuration leaves assessment off. No auto-discovery or silent fallback chooses another provider.

Jev defaults to `https://api.typesafe.ai/v1/systemone` and the `TYPESAFE_API_KEY` environment variable. Laya defaults to `http://127.0.0.1:8765/v1/systemone` without authentication; if the local server requires a key, generate its template with `--api-key-env LAYA_API_KEY`. Populate that variable through a local secret manager or private environment mechanism. Do not paste keys into chat, commands, notes or Git.

## Preview, then explicitly assess

Select the same vault and scope as the active client. Preview first:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" assess "preferred output format" --project demo --advisor-config "C:/Private Config/advisor.json" --preview
```

Preview prints eligible endpoint/payload pairs but sends nothing and does not read credentials. Inspect these private outputs locally; do not post them as diagnostics. With a reviewed shadow configuration and approved content, remove `--preview` to send the bounded request. For Jev, add `--allow-remote-query` to explicitly permit query transmission; without it no remote assessment is made.

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" assess "preferred output format" --project demo --advisor-config "C:/Private Config/advisor.json" --allow-remote-query
```

Use `--personal` instead of `--project demo` only for the user's explicitly chosen personal selection. The output contains ordinary local recall under `context`, advisory status under `advisor`, and separate `assessments`. Inspect status and reason, not process exit alone. A missing key, unavailable server or rejected response leaves local recall usable with a degraded notice. No automatic retry is made.

Jev receives only admitted shared/public records with `remote_allowed=true`, with the same policy applied to their source dependencies. Private records are not sent, even when a remote flag is set. Existing notes are not silently relabeled or opted in. Query transmission needs the separate flag because a query can itself contain private information. Laya uses the fixed local selection, including its permitted private notes, but must be on a loopback address; redirects, proxies and remote fallback are not followed.

The packet is checked for source and sharing changes around provider calls. Stale advice is discarded, and local recall is refreshed. Responses must match the fixed question, valid labels and model routing; malformed or truncated responses are not accepted as complete advice. Confidence is provider-specific and is not a common quality threshold.

## Jev prerequisites

Jev is TypeSafe's hosted decision model. Obtain the intended account/key through the provider's normal process and inspect its billing before authorizing a live request. An existing Claude/Codex subscription does not establish access to this API. This connector uses HTTP directly; a separate SDK is unnecessary.

Protocol and model references inspected on 2026-10-10: [official quickstart](https://docs.typesafe.ai/introduction/quickstart), [models](https://docs.typesafe.ai/models), and [OpenAPI](https://api.typesafe.ai/openapi.json). The example pins `jev-1.13.0`; verify availability for the intended account before use. Installing an SDK is not a local installation of Jev weights.

## Laya prerequisites

Prefer an existing compatible local server. If the user chooses new provisioning, explain that package installation and first startup can download dependencies and model weights. Confirm the chosen model and local resources first. Keep this environment separate from the memory runtime and vault.

The following commands are based on Laya 0.4.2's published server contract; they have **not** been executed as a live inference acceptance test here:

```powershell
python -m venv C:/Tools/laya-env
C:/Tools/laya-env/Scripts/python.exe -m pip install 'laya[serve]==0.4.2'
$env:LAYA_HOST = '127.0.0.1'
$env:LAYA_PORT = '8765'
$env:LAYA_MODELS = 'multilingual'
$env:LAYA_DEFAULT_MODEL = 'multilingual'
$env:LAYA_AUTO_TASK = '0'
$env:LAYA_PRELOAD = '1'
$env:LAYA_JEV_STRICT = '0'
C:/Tools/laya-env/Scripts/laya-serve.exe
```

On macOS/Linux use the environment's `bin/python` and `bin/laya-serve`, with equivalent environment assignments. Bind to loopback rather than the server's public-interface default. Keep full responses (`LAYA_JEV_STRICT=0`) so routing and truncation can be checked. The connector request must name the selected checkpoint, such as `multilingual`; do not substitute a Jev model ID. A `/health` response establishes liveness only.

The package version does not pin model weights. Actual hardware performance, provider answer quality and a compatible weight revision remain unverified. Sources: [Laya package](https://pypi.org/project/laya/0.4.2/) and [server implementation at the inspected revision](https://github.com/NandhaKishorM/laya/blob/68804629e8ccd9d616d48a40e87de9fabbeae069/laya/serve.py).

## Verification scope

Tests use synthetic official-protocol responses and real loopback HTTP fixtures to exercise transport, scope, egress, freshness and failure handling. They do not establish live Jev/Laya readiness or useful judgment quality. No provider inference, model download or billing activation was performed for these tests. Assist mode, semantic embeddings, automatic advisor calls and canonical provider writes are not implemented.
