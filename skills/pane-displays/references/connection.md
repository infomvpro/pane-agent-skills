# Connection and authorization

| Surface | Address | Purpose |
| --- | --- | --- |
| Product | https://pane.ink | Public information |
| Dashboard | https://app.pane.ink | User-owned groups, devices and integration configuration |
| MCP | https://mcp.pane.ink/mcp | Streamable HTTP MCP endpoint for agents |
| REST API | https://api.pane.ink | HTTP integrations and optional helper scripts |

Prefer the client's native MCP connection and OAuth for interactive agents. Pane
advertises authorization-code + PKCE S256 and refresh-token support. The issuer is
`https://api.pane.ink/`. Let the client perform discovery, registration, state/issuer
validation and refresh. The MCP resource is `https://mcp.pane.ink/mcp`.

Requested scopes are `mcp:access`, `display:read`, and (only when publishing or
rendering previews is required) `render:write`. The user selects permitted groups
during consent. A new display in an already authorized group does not inherently
require another consent flow. A different group or missing scope can.

Reading stored card data with `get_frame_content` additionally requires explicit
`content:read`; request it only for revisions/history requiring private payloads.
Existing OAuth grants, refreshes and default API keys do not automatically gain
this permission. Operation recovery is read-only but requires `render:write` and
the same actor that submitted the write.

An API key remains an alternative for systems without OAuth. It is group-bound;
use a key with only the scopes needed. Pass it through the client's secret/env
facility, not a source file or command-line literal. Do not pass device credentials
or the user's dashboard password as an agent API key.

Skill installation and MCP connection are separate. After setup, use one useful
read such as `list_displays`; a successful `tools/list` alone does not establish
that protected operations are authorized. Do not reset other MCP connections.

## Callback and scope compatibility

Pane accepts a varying port for a **registered HTTP loopback callback** on
`localhost`, `127.0.0.1` or `[::1]`. The hostname, path, parameters and query must
still match the registered URI. These hostnames are not interchangeable, HTTPS
redirects must match exactly, and other domains do not get a port exception.
Let the client choose and listen on its port; do not edit the authorization URL.
The token exchange must use the exact redirect URI from that login attempt.

A client ID metadata document (CIMD) may omit `scope`. In that case Pane permits
requests for its supported MCP scopes, including `content:read`; this is only a
request ceiling, not permission already granted. An explicit metadata scope
still restricts what can be requested. Dynamic registration without a scope and
an authorization request without a scope retain the three defaults:
`mcp:access display:read render:write`. Consent determines the approved subset
and groups; refreshing an existing grant never adds `content:read`.

## Remote agents

`localhost`, `127.0.0.1` and `[::1]` in a callback refer to the browser's machine. If Hermes runs on a server but
the browser is on a laptop, the redirect cannot reach that server automatically.
Use the client's supported remote callback flow or an SSH local port forward for
the **actual callback port of this login attempt**. Keep the callback listener and
login process alive. Do not restart OAuth repeatedly or paste callback codes into
agent chat, issue trackers or logs. Pane's checked metadata does not advertise a
device-code grant; do not promise that flow.

## REST fallback

The `/mcp/...` routes on **api.pane.ink** are ordinary REST, not MCP JSON-RPC:

| Method/path | Meaning |
| --- | --- |
| GET `/mcp/displays` | Authorized displays |
| GET `/mcp/displays/{id}` | One display |
| GET `/mcp/displays/{id}/status` | Current publication and ACK evidence |
| GET `/mcp/displays/{id}/frames?limit=10` | Recent frame metadata |
| GET `/mcp/displays/{id}/frames/{frame_id}/content` | Stored cards/context; `content:read` |
| GET `/mcp/displays/{id}/operations/{operation_id}` | Recover write outcome; `render:write`, same actor |
| POST `/mcp/displays/{id}/render/preview` | Render without publication |
| POST `/mcp/displays/{id}/render` | Render and publish |
| POST `/mcp/displays/{id}/notify` | Short temporary alert |

Use `Authorization: Bearer <API key>` over HTTPS. Do not reuse an arbitrary OAuth
access token against a different audience. For REST rendering, use
[main-rest.json](../examples/main-rest.json) or
[temporary-rest.json](../examples/temporary-rest.json). REST notification bodies
use the MCP notification fields except `display_id`, which is in the path.
Registry HTTP responses provide metadata, not full card JSON Schema; obtain full
schemas with MCP `get_card_schema`. See the live [OpenAPI document](https://api.pane.ink/openapi.json)
for the installed REST contract, not for permission to invoke admin endpoints.
