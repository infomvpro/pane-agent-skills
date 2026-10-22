# Security

The read-only helpers never publish to a display. The status helper sends an API key only
to the configured trusted API origin; preview downloads use signed links with no
additional Authorization header. Redirects and environment proxies are disabled.
Do not disable certificate verification or add a token-cache reader to work around
an authentication failure.

Keep tokens, callback URLs, signed previews, audio, transcripts and account-specific
payloads outside Git. The `private/` directory is ignored, but a gitignore is not a
data-loss prevention mechanism. Review staged files before publishing. There are
no real credentials in the example fixtures.

Report sensitive findings through GitHub private vulnerability reporting if enabled
for this repository; otherwise contact the repository owner through their published
private contact channel before providing sensitive details. Do not open a public
issue containing credentials or user content. Public issues can contain a sanitized
reproduction using fictional data.

Compatibility notes identify unverified server features; they do not authorize
probing other accounts or weakening authorization controls.

## Optional voice receiver

The opt-in receiver verifies v2 HMAC, time, group/display allowlists and payload
before persisting an event. It binds to loopback and needs a trusted HTTPS proxy
with buffering, body/time limits and rate limiting. SQLite is private local storage;
there is no multi-replica support or automatic queue quota. Monitor disk and backlog.

Its worker executes an explicitly configured trusted adapter. That adapter can have
external effects; protect its code, credentials and operator policy separately from
event data. Signature validity authenticates Pane delivery, not the speaker. Never
use a transcript as a shell command, a policy change or a grant to another group.
Recheck current display membership before acting. Crash/timeout outcomes are queued
for manual review rather than automatically repeating uncertain side effects.

Completed payload bodies can be purged while keeping deduplication IDs/hashes.
Pending jobs, native agent data and backups require their own retention policy.
See [voice setup](skills/pane-displays/references/audio-webhooks.md) for limits and
acceptance tests. No production receiver or model is installed by this repository.
