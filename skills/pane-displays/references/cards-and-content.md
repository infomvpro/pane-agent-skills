# Cards, content and automatic layout

## Ownership

The agent supplies facts, wording, card types, order and relative content priority.
The display's profile supplies resolution, palette and orientation; the selected
theme supplies styling. Pane composes and renders the result. The device downloads
an encoded frame: it does not execute agent HTML or Tailwind.

Use the actual `get_display`/discovery result for dimensions and orientation.
Two displays with the same diagonal size can have different resolution/palette.
Four grey levels, four colours and six colours are different capabilities; neither
the agent nor a theme can add colours the panel cannot display.

Do not send `layout_hint`, `preferred_span`, theme overrides or hardcoded grid
coordinates for normal cards. Legacy schema fields may still exist; they are not
needed for automatic composition. `get_display_layouts` is optional diagnostic
information, not a mandatory first call or a menu to ask ordinary users to choose.

## Envelope and schemas

MCP `render_display_content` receives `display_id`, `cards`, and optional view
options. Each card uses `type`, `data`, optional `id`, and `priority` (0–1000;
default 100). Explicit stable IDs make a prepared payload easier to inspect, but
they are not a partial-update API. A render supplies the whole new view, not a
patch to one existing card. Do not replace a complex view with one changed card
unless that is the user's intended result. Use `get_frame_content` with explicit
`content:read` to obtain the old cards, then perform a guarded whole-view revision;
see [lifecycle](lifecycle.md#read-and-revise-stored-content).

`get_card_schema(card_type)` returns `schema_available`, `required_fields`,
`properties`, and the complete `schema`. Use the actual types and enums; plain
English descriptions do not override them. Do not invent fields such as
`temperature` when the field is `temp_c`. If a schema is unavailable, do not guess:
choose a known suitable card or explain the unsupported request.

| Common intent | Candidate to discover/use | Bundled snapshot |
| --- | --- | --- |
| Heading and prose | `text.block`: `title`, `body`, optional `footer` | Yes |
| Current weather | `weather.summary`: `location`, numeric `temp_c`, `condition` | Yes |
| Agenda | `calendar.agenda`: ordered `entries`, optional `date`, `calendar` | Yes |
| Styled alert card | `notification.simple`: `title`, `message`, optional `level` | Yes |
| Image inside a themed card | `image.url` | Fetch live schema |
| Custom structured composition | `canvas.custom` | Fetch live schema |
| User-supplied full-frame artwork | `raw.frame`, as the only card | Fetch live schema |

The catalogue is larger than these examples and changes independently of this
package. Discover it once when needed. Use native chart/list/agenda cards when
available instead of turning structured data into a screenshot. For remote images,
use a user-authorized reachable source; do not expose private files on a public
host or bypass server URL restrictions to make an image load.
`canvas.custom` uses a constrained block schema; it is not arbitrary HTML/JavaScript.
Read that schema before using it rather than improvising a markup language.

## Capacity and overflow

The current render contract accepts 1–24 cards. **24 is an input limit, not a
promise that 24 cards fit on any screen.** Text length, card semantics, image
ratio, orientation and panel resolution all affect layout.

Use a small coherent summary on a small display; place detail on a larger one
only when the content warrants it. There is no authoritative fixed "4.2 inch = N
cards" table. Prefer a concise agenda and a short note over six dense cards. On
larger screens a compact multi-topic summary can be appropriate. The current composer retains cards and reports
`composition.status`, condensation notes and warnings. A 422 can require shorter
content or fewer cards; 503 can indicate a bounded composition search/timeout.
Inspect a preview for unfamiliar density; do not silently discard important data. Do not increase input count repeatedly until a render fails.

Card priority expresses content importance. Temporary-view priority controls
which temporary view may replace another. They are separate levels of priority.
Use list order for intended reading sequence but do not treat order as fixed pixel
coordinates. Offset timestamps should include an offset; local times such as
`09:00` remain local strings. Do not fabricate current weather or calendar entries.

## Examples

- [main-summary.json](../examples/main-summary.json): a modest persistent summary.
- [temporary-notice.json](../examples/temporary-notice.json): a 3-minute structured notice.
- [notification.json](../examples/notification.json): a short alert through the dedicated tool.
- [multi-display.json](../examples/multi-display.json): two separately tailored views. Iterate
  `renders` as individual tool calls after resolving both targets; no atomic batch exists.
- [main-rest.json](../examples/main-rest.json) / [temporary-rest.json](../examples/temporary-rest.json):
  REST bodies, where temporary options are nested in `temporary_view` and every card needs `id`.

Also see [preview.json](../examples/preview.json),
[revision-main.json](../examples/revision-main.json) and
[notification-rest.json](../examples/notification-rest.json).

All examples contain fictional information, non-live IDs and **placeholder keys**.
Generate a fresh key for each new logical publication and preserve it only for
identical retries; never reuse the checked-in example keys for real operations.
Replace the illustrative expected version with the observed display version.
Preview omits both publication fields. The validator uses four dated example schemas; see
[schema provenance](../schemas/provenance.json). Schema success does not prove
content accuracy, target access, pixel fit or deployed feature support.
