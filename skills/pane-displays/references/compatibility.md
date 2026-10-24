# Compatibility record — 2026-10-22

Package version: **0.3.1**. Live tool schemas remain authoritative. The public
package is self-contained and does not require access to the application repo.

| Evidence | What was checked |
| --- | --- |
| Hosted REST metadata | OpenAPI render/notify idempotency and version fields, content/operation routes |
| Hosted OAuth metadata | `mcp:access`, `display:read`, `render:write`, explicit `content:read` |
| Deployed source | MCP tools, content reads, v2 webhook delivery and four bundled card schemas matched maintained source SHA-256 on 2026-10-21 |
| Maintained contract | Pending/terminal publication states, retention, no-main fallback and exact ACK semantics checked against the maintained service implementation |
| Package validation | Offline payload/schema regressions, synthetic HTTP/ACK cases, compact-skill export and current application contract comparison |
| Claude Code compatibility | Fresh consent, code-to-token exchange and a protected display-list read verified against the hosted service on 2026-10-21 |
| Isolated OAuth regression | Claude/Codex public metadata, PKCE, scope/group boundaries, code exchange, refresh and existing Codex grant compatibility passed the server release checks |
| Outside package validation | Long-running hosted OAuth refresh, real-account publication, physical panel/firmware operation, external webhook delivery and live-model evaluation |

Deployed capabilities now used by this skill:

- render/notify `idempotency_key`, `expected_publication_version` and
  `get_publication_operation`; defaults/expiry are bounded, not permanent promises;
- `get_frame_content` with separately granted `content:read`; historical payload
  availability/context are explicit, with 410 and unknown provenance handled;
- server expiry selects latest main or “Waiting for content” without a main;
- durable audio processing and webhook delivery with the v2 signature contract;
- strict card data validation, including nested agenda fields.

Still not provided: atomic multi-display batches, `queue`/background scheduling,
a universal cards-per-inch table, bit-identical historical replay, or guaranteed
offline expiry on every firmware. Theme/layout selection remains automatic.

Four schemas are bundled as example snapshots; exact hashes and review evidence
are in [provenance.json](../schemas/provenance.json). Fetch `get_card_schema` for
unfamiliar types. HTTP registry `data_schema_ref` values are internal references,
not public URLs. The local validator is a stricter authoring profile, not a full
server emulator; it cannot establish authorization, image reachability or pixel fit.

The GitHub skill's common instructions generate the compact website skill using
`tools/export_compact.py` in the repository root. Reference/helper sections stay
in this full package; install one variant per agent. The application documentation
build then regenerates its Markdown/ZIP and web snapshot. Source synchronization
does not itself publish the website or change an installed agent's skill.

Voice package 0.3.1 is checked against the maintained server's `_webhook_payload`,
signing functions, owner webhook routes and delivery behavior. Receiver tests use
synthetic loopback HTTP, SQLite restart/replay and real bounded subprocesses.
They do not prove a public deployment, model execution or end-to-end physical audio.
The complete website ZIP carries the same files as the GitHub skill; the compact
Markdown/ZIP remains available for instruction-only installs.
