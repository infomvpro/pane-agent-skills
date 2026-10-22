# Publication lifecycle

```text
User intent -> authorized display -> structured card JSON
  -> Pane automatic composition/theme/palette -> server publication
  -> device polling/download -> physical refresh -> device ACK
```

There are independent facts: rendered, published, current on the server, downloaded,
and device-reported displayed. A preview or render-job ID proves none of the later
steps. An offline e-paper panel can continue showing old pixels indefinitely.

## Main, temporary and notifications

| Operation | Use | Lifetime |
| --- | --- | --- |
| Main render | Persistent base information | Until replaced |
| Temporary render | Multiple/structured cards for a limited period | Explicit `ttl_sec`, 5–3600 |
| Notification | Short title/message alert | `ttl_sec`, 5–3600; default 45 |

Temporary default priority is 500; notification default is 700. Default temporary
conflict policy `replace_lower_priority` replaces only a lower-priority active
temporary view. Equal/higher priority can produce `temporary_view_busy`.
`drop_if_busy` declines while a temporary view is active. `replace_current` is an
intentional override, not a retry technique. `queue` is not supported by the
checked implementation even if an input enum mentions it.

TTL begins on **server publication**. Rendering time and device download/refresh
time are distinct. A short-lived notification may expire before an offline or slow
device shows it. Server expiry cannot physically erase an unpowered display.

Updating main while a temporary view is active can save the new base without
making it current (`published: true`, `current: false`). After expiry the server
returns to the latest main. Do not say that this hidden main was already displayed,
and do not poll its original publication version as if it were current.

When no main exists, expiry selects a neutral **Waiting for content** frame.
This fallback is deployed. A connected device obtains it through polling; it does
not erase an unpowered panel. Local offline expiry/main caching depends on the
model's firmware and must not be promised for all displays.

## Evidence and bounded waiting

From the render result retain `frame._id`, `publication_version`, `published`, and
`current`. Do not infer the frame ID from the render-job ID. For a currently
published frame, examine `get_display_status(display_id)`:

- `current_frame.frame_id` and its `publication_version` match the target;
- `current_frame_ack.frame_id` matches;
- ACK has `validated: true`, `status: "displayed"`, matching publication version;
- ACK's offset timestamp is not earlier than the current `published_at`.

An old `displayed` ACK for reused content is insufficient. A `fetched` ACK is not
a refresh completion. A newer publication may have superseded the target.
Validated `failed`, `unsupported_frame` or `render_failed` is a device failure.

Check at about 5-second intervals for at most 120 seconds / 24 reads by default;
adapt a finite budget for slow panels. Stop on confirmed display, failure, a
changed publication, authorization failure, cancellation or budget expiry. On
timeout say "not yet confirmed", not "failed to publish". The optional
[wait helper](scripts.md) implements these checks for API-key users; OAuth users
should use the same logic with native MCP rather than extracting tokens.

## Retry and concurrent writers

For every new logical render/notification, create a fresh `idempotency_key`
(1–128 ASCII letters, digits, dot, underscore, colon or dash). Keep the exact
payload, target, tool and actor for retries. Keys are scoped to actor, group,
display and operation kind; do not switch accounts, API keys or OAuth grants to
recover. Native access-token refresh within the same OAuth grant keeps the actor.
The API fields are optional, but using a key is the skill's normal write workflow.

- Lost response: repeat the exact keyed write. Do not generate another key.
- `operation.status: pending`: use `get_publication_operation(display_id,
  operation.id)` and respect `retry_after_sec`; REST uses 202 and `Retry-After`.
  Missing frame data in a pending result is not an error or a successful publish.
- `published`: the original write succeeded; check `current` and the separate ACK.
- `superseded`: the original write succeeded but is no longer current or retained
  main. Replaying the key returns evidence and does **not** restore old content.
- `failed` / interrupted: the old key does not re-render. Inspect the error and
  decide explicitly whether a genuinely new write is appropriate.
- `idempotency_key_payload_conflict` (409): changed payload under the same key;
  stop. Do not disguise a retry as new content.
- `publication_operation_expired` / unavailable (410): evidence/retention expired.
  Reconcile current state; do not assume replay is safe. Default retention is
  seven days, configurable; `operation.expires_at` is authoritative. After record
  cleanup an old key cannot provide deduplication indefinitely.

Use `expected_publication_version` from a fresh observed display state when a
write depends on that state. A matching keyed retry is resolved before this guard;
do not update its expected version on retry. A new write with a stale version
returns 409: reread, preserve newer changes, and reconsider the intended edit.
Never loop over freshly fetched versions until an overwrite succeeds.

Bound transient write recovery to three attempts; bound operation-status polling
to ten reads within 120 seconds, respecting server delays. A server delay longer
than the remaining budget ends the wait without an early retry. A missing scope,
revocation or invalid input is not transient. If the original write had no key,
read status and a small history instead of attaching a new key after the fact.

For multiple displays, publish per target with its own key and report each result.
There is no atomic batch, built-in queue or synchronized physical refresh. Never
roll back a successful target merely because a different one failed.

## Read and revise stored content

1. Identify the intended current or main frame from status/display state. A
   temporary current frame is not the main. Recent history can include drafts;
   do not choose the newest rendered frame as proof of published main.
2. Call `get_frame_content(display_id, frame_id)` with explicit `content:read`.
   It returns normalized `render_request`, `display_publication_version`,
   `publication_state`, `compatibility` and known `provenance`.
3. Check `compatibility.can_render_with_current_schema`. Refresh only affected
   schemas when needed. `provenance_status: legacy_unknown` is not invented old
   context; missing payloads/system frames return 410 `content_revision_unavailable`.
4. Preserve unrelated cards and edit only the requested data. Set
   `expected_publication_version` to the returned **display** version, give this
   new write a fresh key, and send the complete new view. The old frame's own
   `publication_version` can be null or historical and is not the guard.

For MCP, map `render_request.temporary_view.ttl_sec/reason/priority/conflict_policy`
to `ttl_sec/temporary_reason/temporary_priority/conflict_policy`. For main, omit
`temporary_view: null` and all temporary options. REST uses nested `temporary_view`.
Neither path accepts the whole content-response wrapper as a render request.
Temporary replay is a new publication with a new TTL, not resumption of the old one.

[revision-main.json](../examples/revision-main.json) shows a full view with only
its note changed. Its version `12` is illustrative: substitute the version returned
by the actual read. Identical source data may render differently after schema,
theme, timezone or renderer changes; bit-identical replay is not guaranteed.

## Finite rotations

For an explicitly requested finite sequence, agree on target, content, dwell time,
maximum steps/end time and final state. Keep the canonical payload locally so the
sequence does not depend on reconstructing original card JSON from a PNG/history.
Allow for full e-paper refresh latency. Stop on another writer's change or ambiguous
write; do not blindly restore an old main over newer content.

This package deliberately does not ship a background publisher/rotation daemon.
Use the deployed idempotency/version guards for each step of a user-authorized
sequence, with a finite budget and these same stop conditions. Server write safety
does not supply a scheduling service or authorize background publishing.
