# Codex

Connect only if Pane is not already configured:

```sh
codex mcp add pane --url https://mcp.pane.ink/mcp --oauth-resource https://mcp.pane.ink/mcp
```

If authentication is still required:

```sh
codex mcp login pane --scopes mcp:access,display:read,render:write
```

Complete the browser consent for the intended groups. On a remote host, use the
installed CLI's supported `--no-browser` flow or a callback tunnel; check
`codex mcp login --help`. Never ask the model to read the OAuth token store.

For an API-key connection **instead of OAuth**, configure:

```sh
codex mcp add pane --url https://mcp.pane.ink/mcp --bearer-token-env-var PANE_API_KEY
```

Provide the key securely to the environment of the process running Codex. Avoid
overwriting an existing working Pane connection. The YAML metadata in this skill
describes the MCP dependency; it does not grant scopes or supply credentials.

Install the skill folder using the client's skill installer, or as a project skill
under `.agents/skills/pane-displays`. Invoke `$pane-displays` or describe a Pane
display task. [Official skill documentation](https://learn.chatgpt.com/docs/build-skills).

The MCP command options above were checked against the local Codex CLI help on
2026-10-20. OAuth sign-in was not repeated as part of packaging this skill.

For revisions that read existing cards, also request `content:read` explicitly
through this client’s supported consent/scope flow. In Codex’s example `--scopes`
list this is an additional comma-separated scope. Existing grants do not gain it
on refresh; do not request it merely to publish new supplied content. See
[connection and authorization](connection.md).
