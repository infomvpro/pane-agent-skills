# Changelog

## 0.3.0 — 2026-10-22

- Add an opt-in v2 webhook receiver with durable SQLite acceptance, group/display
  allowlists, delivery/event deduplication, a bounded worker and explicit recovery.
- Add synthetic audio/test events, a receiver schema, operator-owned voice policy,
  a durable file-inbox adapter example and restart/replay/error/security tests.
- Document owner-only registration, native gateway discovery, signature vs speaker
  identity, current device binding checks and separate acceptance/publication/ACK.
- Synchronize common website instructions and add a complete downloadable package.

## 0.2.1 — 2026-10-21

- Clarify registered loopback callbacks with dynamic ports, remote-agent listeners,
  CIMD scope limits, explicit consent and callback/scope troubleshooting.
- Document Claude Code callback compatibility and scope troubleshooting.
- Synchronize the compact website skill with this package. No card-schema,
  example-payload, helper-script or MCP endpoint changes.

## 0.2.0 — 2026-10-21

- Document deployed keyed publication recovery, pending/terminal outcomes,
  version guards, explicit content reads and no-main expiry fallback.
- Specify deployed v2 webhook signatures, delivery deduplication and audio 202 semantics.
- Refresh all four example card schemas, including strict nested agenda validation.
- Validate publication fields, distinguish MCP preview and REST notification inputs,
  add guarded revision/preview/REST examples, and respect Retry-After in ACK reads.
- Generate the compact application skill from the same common instructions; add
  a read-only application contract/schema drift check and regression fixtures.
- Preserve group/scoped access, private content handling, bounded polling and
  separate server publication/device ACK semantics. No publishing daemon added.

## 0.1.0 — 2026-10-20

- Initial `pane-displays` skill with progressive references and client setup guides.
- Content-driven automatic layout, lifecycle, efficient discovery and exact ACK guidance.
- MCP and REST examples; four dated example card schema snapshots.
- Offline payload validation, bounded status reads and private preview bundles.
- Local regression tests, manual agent behaviour cases and GitHub Actions validation.
- Explicit compatibility limits for pending server audit features; no production
  publication or authenticated client end-to-end test performed during packaging.
