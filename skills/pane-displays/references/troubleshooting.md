# Troubleshooting without request storms

| Observation | Action |
| --- | --- |
| No Pane tools | Check MCP configuration/connection, not the display firmware. Skill installation alone does not connect MCP. |
| Tools list works, display read fails | Check authentication and granted groups/scopes. Tool enumeration is not an authorization test. |
| `redirect_uri_not_registered` | Start one fresh native sign-in after a server compatibility update. If it persists, check the client's registered callback host/path/query; a dynamic port is allowed only for a matching HTTP loopback URI. Do not edit URLs or reuse callback codes. |
| `scope_not_registered` | Requested scopes exceed the client's registration/metadata limit. Use the client's supported configuration; a fresh grant is needed for new permissions, while refreshing an old grant cannot add them. See connection reference for omitted CIMD scope semantics. |
| OAuth callback opens localhost on laptop, agent runs remotely | Use the active client's remote callback flow/tunnel; see connection reference. Do not start three competing logins. |
| 401 | Let native client refresh once; reauthenticate only if required. Never repeatedly refresh from multiple processes. |
| 403 / display absent | Check scope/group selection and current membership. Do not broaden permissions silently. |
| Unknown card/schema mismatch | Refresh only that card's schema and fix the fields. Do not enumerate every schema again. |
| HTTP 429 | Respect server backoff; stop a tight loop. Helper reads use bounded backoff. Recover keyed writes using the lifecycle contract; never blindly retry an unkeyed write. |
| Write timeout or disconnected response | Repeat the exact keyed request or read its operation ID; without an original key, read status/history. Bound recovery. |
| `operation.status: pending` / HTTP 202 | Not yet published. Poll `get_publication_operation` within budget and server delay. |
| Version conflict (409) | Reread state and preserve the other writer's changes; do not auto-bump the guard and overwrite. |
| `idempotency_key_payload_conflict` (409) | Same key was used for changed content; stop and distinguish retry from a new intent. |
| Operation expired/unavailable (410) | Reconcile state; old keys do not provide an indefinite guarantee after cleanup. |
| `get_frame_content` 403 / 410 | 403 may need explicit `content:read`; 410 means missing original payload. Do not infer original cards from PNG. |
| `temporary_view_busy` | Explain the current temporary priority; do not switch to override policy without user intent. |
| `published: true`, `current: false` | A saved main may be behind a temporary view. Inspect current state, not just last render result. |
| `displayed` ACK is older or for another version | Not evidence for this publication. Wait within budget or report unconfirmed. |
| No ACK | Check last-seen/connection and failure status. Do not repeatedly republish to wake an offline device. |
| Old temporary image remains | E-paper retains pixels; check expiry, main presence and device connectivity. Connected devices select latest main or Waiting for content; offline local return depends on firmware. |
| Composition condenses content | Inspect notes/warnings and preview if useful; shorten deliberately or use a more suitable native card. |
| Composition 422 / 503 | 422 can identify content that needs shortening; 503 can indicate a bounded composition search/validation limit. Inspect the safe error details; do not brute-force layouts or loop writes. |
| Preview URL fails | It may have expired. Obtain a fresh authorized reference; never expose access tokens or disable TLS. |
| Transcript appears, receiver does not get it | Check webhook configuration and delivery evidence separately. No configured receiver is not a transcription failure. |

Keep diagnostic reports small: operation, target (when appropriate), status code,
frame/publication version, relevant warning and final evidence. Redact secrets,
signed URLs, callback codes, unrelated account data and private transcript bodies.
Do not invoke reset/remove/admin actions to solve a rendering problem unless the
user actually asks for that action.
