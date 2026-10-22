# Hermes

Merge this entry into the existing `mcp_servers` section of Hermes configuration;
preserve all other servers:

```yaml
mcp_servers:
  pane:
    url: "https://mcp.pane.ink/mcp"
    auth: oauth
```

Then run `hermes mcp login pane` in an interactive terminal. Complete group/scope
consent, reload MCP or start a new session, and test a protected display read.
Install `pane-displays` under the skill directory for the active Hermes profile
(normally `~/.hermes/skills/pane-displays`).

For a remote server, keep login active and forward its actual callback port from
the laptop with `ssh -N -L PORT:127.0.0.1:PORT USER@HOST`, substituting the real
port and SSH destination. Use the client's private terminal callback-paste flow
only if that version offers it. Never paste the URL into model chat or manually
edit cached tokens. Pane does not currently advertise device-code authorization.

See [Hermes MCP documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
and [OAuth over SSH](https://hermes-agent.nousresearch.com/docs/guides/oauth-over-ssh).
This setup was documentation-reviewed; no new live Hermes login was performed.

Reading original stored cards for revisions additionally needs explicit
`content:read` consent. Existing grants do not gain it on refresh. Request it
through the client’s supported scope flow only when needed; see
[connection and authorization](connection.md).

For incoming voice, follow [audio webhook setup](audio-webhooks.md). Prefer the
installed Hermes runtime's native durable ingress/worker integration when available.
A background cron agent is one deployment choice, not a Pane requirement. Do not
assume a particular model, Telegram account or cron command exists. Configure the
actual adapter and test one real event through it before reporting voice as ready.
