# MCP operation map

Names below are the Pane tool names. A client may prefix them with its server
name. Use its discovered tools and current schemas; do not manufacture tool names
from REST paths. This is a routing reference, not a checklist of calls to make.

| Tool | Main input | Use/effect |
| --- | --- | --- |
| `check_epaper_api` | None | Connection diagnostic; not required before every update |
| `list_groups` | None | Authorized group discovery |
| `list_displays` | None | Displays visible to this connection |
| `list_group_displays` | `group_id` | Targets in one authorized group |
| `get_display` | `display_id` | Current device/profile/settings information |
| `get_display_layouts` | `display_id` | Optional layout diagnostics; ordinary content uses automatic layout |
| `get_display_status` | `display_id` | Current server publication, connection and ACK evidence |
| `list_card_types` | None | Discover card types/metadata |
| `get_card_schema` | `card_type` | Exact content fields, types, required fields and full schema |
| `list_themes` | None | Theme catalogue; does not change a device's theme |
| `list_display_types` | None | Supported profile catalogue; does not change a physical device |
| `list_recent_frames` | `display_id`, optional `limit` | Recent metadata/preview links; use a small limit (current maximum 50) |
| `preview_display_content` | Content/view arguments only; no idempotency/version arguments | Creates a preview/render job, **no device publication**; requires render scope |
| `render_display_content` | `display_id`, `cards`, view options | Creates and publishes/saves a main or temporary view |
| `send_temporary_notification` | `display_id`, `title`, `message`, optional TTL/priority/level | Publishes a temporary alert |
| `get_publication_operation` | `display_id`, `operation_id` | Recover a write result; same actor and `render:write` required; never republishes |
| `get_frame_content` | `display_id`, `frame_id` | Read original card data and known rendering context; explicit `content:read`; never publishes |

The render/preview view options are `view_mode`, `ttl_sec`, `temporary_reason`,
`temporary_priority`, `conflict_policy`. Use the [examples](../examples/main-summary.json)
and [lifecycle](lifecycle.md) for their meanings. Deprecated hints may appear in
cached clients; do not use them to drive normal composition.

Only the two publishing tools additionally accept `idempotency_key` and
`expected_publication_version`. Preserve both with the exact payload on retry.
`operation.id` is used for operation recovery; it is not a frame/render-job ID.
Pending results include `retry_after_sec` and do not establish publication.
See [lifecycle](lifecycle.md) for conflicts, expiry and content revisions.

MCP resources provide alternative read paths when the client supports resources:

```text
epaper://project/context
epaper://groups
epaper://groups/{group_id}/displays
epaper://displays
epaper://registry/cards
epaper://registry/themes
epaper://registry/display-types
epaper://rendering/guide
epaper://cards/{card_type}/schema
```

Do not load both the resource and equivalent tool response for the same discovery.
The older `epaper://` namespace is intentional; do not substitute `pane://`.
No checked MCP tool creates/removes/claims a device, resets firmware, manages
Wi-Fi, changes theme/orientation/group membership, starts recording, or registers
a webhook. Those require the appropriate separate user/admin workflow.
