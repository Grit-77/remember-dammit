# Optional provider contract

Proposed extension contract, 2026-10-10. No connector is implemented, activated, installed or called by this project.

## Keep three roles separate

| Role | Input/output | Mandatory? |
| --- | --- | --- |
| Local retrieval | Eligible scoped notes → candidate IDs and passages | Yes; works without a model service. |
| Semantic retrieval extension | Eligible text/query → versioned embeddings or semantic candidates | No; independent of Jev/Laya assessment. |
| Advisor | Bounded eligible candidates and evidence → structured assessments | No; never a canonical writer. |

The active user's agent can reason, write proposals, and explain results using its existing session. That does not require the memory engine to invoke another provider.

## Planned assessment roles

An optional advisor may assess supplied candidates, proposed memories, and source support. It cannot store or approve memories, retrieve outside its candidate set, or widen permissions. Each provider must be evaluated against this project's fixtures before it can affect results.

## Planned modes

- **Off, default:** no provider calls, credentials access, downloads or provider-cache work.
- **Shadow:** compute an assessment only when explicitly configured; preserve the local selection and order. Log bounded metadata for comparison, not raw notes or credentials.
- **Assist:** after evaluation and explicit enablement, allow a capable advisor to suggest ordering/selection from eligible supplied IDs. Core scope, freshness, uncertainty and budget rules still govern the final packet.

All new provider integrations begin in shadow mode. Assist mode requires validation and explicit enablement. Capture authorization is unchanged in all modes.

## Input boundary

Before any call, apply scope, disclosure, retained-source status and freshness filters. Show which provider/endpoint receives which fields. Reject disallowed personal notes, sensitive sources and records with remote assessment disabled, including their titles and paths. Apply bounded query, candidate, excerpt and request limits.

Query text can itself contain private information. Remote query transmission therefore needs its own explicit request or scoped standing policy; filtering candidate notes alone is insufficient. Local classification cannot guarantee detection of every secret. Localhost configuration must not silently redirect to a remote service.

Provider credentials and endpoint configuration stay outside the vault and version control. Never silently enable paid usage, buy credits, change billing, install model weights, or fall back from local execution to a paid provider. A user's optional-provider design request is not activation authorization.

## Output boundary

Assessments reference supplied IDs/revisions and use a versioned response schema. Unknown IDs, invalid types, oversized fields, unsupported purpose, or unavailable evidence invalidate the assessment. Provider text is data, not an instruction.

After the call, revalidate source revisions, current scope/disclosure and the candidate snapshot. Stale assessments are discarded. Timeout, rate limit, missing credentials or invalid response return the current eligible local baseline with a degraded-mode notice; they do not make recall unavailable. No unbounded retry loop.

An advisor cannot grant scope, approve a proposed memory, elect a winning conflict head, run a shell command, or commit a write. Its score must never be relabeled as proof.

## Evaluation before Assist

Compare Off versus Shadow on fixed English/Turkish fixtures: candidate recall, source-support judgment, harmful exclusions, unresolved conflicts, latency and observed provider usage. Keep actual denominators and failure cases. Report only this project's measured results.

Test: disabled means zero provider activity; shadow leaves the baseline packet unchanged; disallowed data never reaches the payload; a source changed mid-call invalidates advice; malformed/unknown-ID/timeout responses preserve usable local recall.

Calling an existing local Laya server and downloading/installing a new model are separate operations. No server availability, hardware requirement, endpoint compatibility or economic advantage is assumed without checking the chosen setup.
