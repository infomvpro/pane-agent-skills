# Claude Code

Add the remote HTTP server if it is not already present:

```sh
claude mcp add --transport http pane https://mcp.pane.ink/mcp
```

In Claude Code use `/mcp`, choose Pane, and complete authentication. Select the
intended groups and read/render scopes. Keep refresh handling in the client.
Install this skill directory under `.claude/skills/pane-displays` in the relevant
project, or use a compatible skill installer. Do not copy secrets into a shared
project MCP configuration.

These instructions are for Claude Code. Claude web/desktop connectors have their
own installation UI; supplying this skill does not automatically install a connector.
See [official MCP documentation](https://code.claude.com/docs/en/mcp) and
[skill documentation](https://code.claude.com/docs/en/skills).

See the dated [compatibility record](compatibility.md) for verified connection
flows and validation limits.

For `redirect_uri_not_registered` or `scope_not_registered`, start one fresh
native `/mcp` authentication after the server update, with the callback listener
still running. Do not reuse an old URL or hard-code a callback port. If it still
fails, use [troubleshooting](troubleshooting.md); repeating sign-in cannot repair
an incompatible client registration or metadata document.

Reading original stored cards for revisions additionally needs explicit
`content:read` consent. Existing grants do not gain it on refresh. Request it
through the client’s supported scope flow only when needed; see
[connection and authorization](connection.md).
