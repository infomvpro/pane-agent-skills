# Optional CLI helpers

Native MCP is sufficient for ordinary use. The read-only helpers add offline
validation, bounded evidence checking and local preview artefacts. They do not
configure OAuth, read a token cache, render or publish anything. The separate
opt-in voice receiver persists events and its worker invokes a configured trusted
adapter, which can have external effects; see the voice section below.

Requires Python 3.11+; tested locally on Python 3.12. From the **skill directory**:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/validate_payload.py --help
python scripts/wait_for_display.py --help
python scripts/preview_bundle.py --help
```

## Validate a payload

```sh
python scripts/validate_payload.py examples/main-summary.json --strict
python scripts/validate_payload.py examples/temporary-notice.json --strict
python scripts/validate_payload.py examples/notification.json --kind notify-mcp --strict
python scripts/validate_payload.py examples/multi-display.json --kind multi-display --strict
python scripts/validate_payload.py examples/temporary-rest.json --kind render-rest --strict
python scripts/validate_payload.py examples/notification-rest.json --kind notify-rest --strict
python scripts/validate_payload.py examples/preview.json --kind preview-mcp --strict
python scripts/validate_payload.py examples/revision-main.json --strict
```

Default input is MCP render arguments, not a tool-result/JSON-RPC wrapper. The
multi-display envelope is a **local plan**, not a server endpoint. Validation checks
card schemas, payload structure, TTL bounds, duplicate IDs, idempotency key syntax
and strict integer publication versions. Preview rejects publication-only fields;
notify-rest omits `display_id`. Keys are optional in the API; generate a new key
for each logical write and retain it across retries. Local validation does not
check whether a key/version is current on the server.
It intentionally rejects deprecated layout/span fields, the unsupported `queue`
policy and unused temporary options on a main render. This is a stricter authoring
profile than some permissive server parsers; it is not the server's complete schema.
Omit unused optional values instead of sending null. The publication version must
be a JSON integer, not a string, boolean or floating-point value.

Only four example card schemas are bundled. Save an unwrapped `get_card_schema`
result as `private/schemas/CARD_TYPE.schema.json`, then use `--schema-dir private/schemas`.
Raw JSON Schema documents work too. The directory must contain every card type
used in that payload. It accepts only local `#...` schema references and never
fetches external references. Keep the schema directory trusted. Missing schemas
fail explicitly. The bundled schemas reject unknown top-level and nested agenda
fields even without `--strict`. An explicitly permissive external schema can still
produce typo-review warnings (failure with `--strict`). Schema validation cannot
establish meaning,
authorization, image reachability or pixel fit.

Exit `0` means local checks passed; `2` means invalid input/configuration or, with
strict mode, warnings. Output contains rule names and card indices, not card text.

## Wait for a device report

For a user who already has an API key, load it privately in **bash**:

```bash
read -r -s -p 'Pane API key: ' PANE_API_KEY
printf '\n'
export PANE_API_KEY
```

Use the actual render response's frame `_id` and publication version:

```sh
python scripts/wait_for_display.py \
  --display-id YOUR_DISPLAY_ID --frame-id YOUR_FRAME_ID \
  --publication-version 1 --timeout 120 --interval 5 --max-requests 24
unset PANE_API_KEY
```

`1` above is an illustration; substitute the returned version. This helper only
confirms an **exact current publication**. A saved main hidden by a temporary
view returns `not_current`; that does not mean its main save failed. A later return
to main may have a new publication version. Read the fresh status before choosing
what evidence to wait for; never substitute another version just to obtain success.

Exit `0`: validated device-reported display. Exit `3`: unconfirmed, not current,
unsupported evidence or device-reported failure; inspect `state`. Exit `2`: input,
authorization or transport error. `130`: interrupted. Read-only transient errors
respect `Retry-After` (seconds or HTTP date) and back off within the finite
budget; a longer server delay exhausts the budget without an early retry. No
writes are retried. Network operations have
a 10-second timeout cap; an in-flight operation can finish after the polling
deadline. This is not optical verification of the screen.

`--api-base` is a trusted operator setting: the API key is sent to that origin.
Default is `https://api.pane.ink`. Plain HTTP is rejected except literal loopback
with explicit `--allow-http-localhost` for tests. Redirects and environment proxies
are disabled; configure a supported native client if your network requires a proxy.
Do not export OAuth tokens from a client just to use this helper.

## Save existing previews

Save the unwrapped JSON result of `preview_display_content` (or an array of up to
12 such results) in a private file. Signed URLs are temporary credentials.

```sh
python scripts/preview_bundle.py private/preview-responses.json --out private/review-01
```

The output directory must not already exist; its parent must exist. The helper
accepts only signed preview PNG URLs from the configured API origin and known
frame/render-job paths. It sends no API key, refuses redirects, caps each download
at 8 MiB and each decoded PNG at 8 million pixels, and saves originals, a contact
sheet and a manifest without signed URLs. Originals preserve exact bytes; sheet
thumbnails are only for comparison, not colour-accuracy approval.

Outputs are private (directory 0700, files 0600 on POSIX), but still contain the
display content. Keep them out of Git and delete them when no longer needed.
After a failure, partial files can remain; absence of `manifest.json` means the
bundle is incomplete. Do not reuse that output directory or treat partial output
as success. Expired URLs require a fresh authorized preview reference, not token
extraction or making the asset public.

## Voice webhook receiver (opt-in service)

[webhook_receiver.py](../scripts/webhook_receiver.py) has different effects from
the read-only helpers: `serve` listens on loopback and durably writes its inbox;
`work` invokes a fixed trusted executable; `retry` requeues one reviewed event;
`purge-completed` removes completed transcript bodies while retaining replay IDs.
`status` prints counts. Commands exit 0 on a completed CLI operation, 1 on a local
configuration/storage error and 130 on interruption. Worker job outcomes are in
its JSON counts, so a successful CLI exit alone does not mean every job succeeded.
Read [setup, security limits and acceptance tests](audio-webhooks.md) before use.
