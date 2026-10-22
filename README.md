# Pane agent skills

Agent instructions, examples and optional tools for [Pane](https://pane.ink), the
e-paper display system. Agents send structured content; Pane handles automatic
layout, themes, screen orientation and colour capabilities.

**Included skill:** [`pane-displays`](skills/pane-displays/SKILL.md).
It covers display discovery, main/temporary views, notifications, previews,
device-reported acknowledgements, safe retries, guarded content revisions and
voice/webhook setup with a durable receiver and bounded worker. Current package: **0.3.0**.
The package follows the [Agent Skills format](https://agentskills.io/specification).

## Install and connect

Copy the complete `skills/pane-displays` directory into the skill directory used
by your agent, or use your client's skill installer with this repository and path.
Keep `references`, `examples`, `schemas`, `scripts` and `requirements.txt` together.
The helper scripts have no dependency on the private Pane application repository.

For example, from this clone, install into the **current project's** Codex skills
(do not overwrite an existing installation without reviewing it):

```sh
mkdir -p .agents/skills
test ! -e .agents/skills/pane-displays && cp -R skills/pane-displays .agents/skills/pane-displays
```

Equivalent client paths and connection instructions:
[Codex](skills/pane-displays/references/client-codex.md),
[Claude Code](skills/pane-displays/references/client-claude.md),
[Hermes](skills/pane-displays/references/client-hermes.md).
For another compatible client, install the same folder and configure Streamable
HTTP MCP at **`https://mcp.pane.ink/mcp`** using that client's OAuth UI. Installation
does not itself connect or authorize access. API keys remain an alternative.

Then ask, for example:

> Use Pane to show today's agenda on the Office display. Keep it as the main view.

> Send the Kitchen display a three-minute reminder that delivery is arriving.

> Preview a concise weather and agenda summary for my portrait display; don't publish it.

Use actual authorized targets and real source data. Examples contain fictional
facts and IDs. Ordinary updates do not require repeatedly downloading all schemas
or generating a preview first.

## Optional helpers

| Script | Purpose | Network effects |
| --- | --- | --- |
| `validate_payload.py` | Validate MCP/REST JSON against local example/exported schemas | None |
| `wait_for_display.py` | Bounded check of the exact current frame and publication ACK | Authenticated GET only |
| `preview_bundle.py` | Save existing signed previews plus a contact sheet | Signed PNG GET only |
| `webhook_receiver.py` | Verify signed voice events, persist/deduplicate and invoke a trusted adapter | Opt-in loopback HTTP listener; worker executes configured adapter |

See [commands, exit codes and limits](skills/pane-displays/references/scripts.md).
There is no custom OAuth client or token-cache reader. The optional receiver only
runs when explicitly started; installation does not enable a daemon or microphone.
Its worker needs a real host-specific adapter and an owner-authorized policy.
See [voice setup](skills/pane-displays/references/audio-webhooks.md),
[synthetic event](skills/pane-displays/examples/audio/audio-transcribed.json) and
[policy example](skills/pane-displays/examples/audio/voice-policy.md).
The owner registers the webhook because ordinary MCP grants do not administer it.
Dependency installation is only necessary for helper scripts.

## Validation for maintainers

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

CI runs the same tests on Python 3.12. Tests use synthetic data and a local HTTP
server; no Pane credentials or production writes are needed. Manual agent behaviour
scenarios are in [tests/behavior-cases.json](tests/behavior-cases.json); they are an
evaluation rubric, not a claim that live agents were run.

Read the dated [compatibility record](skills/pane-displays/references/compatibility.md)
for the deployed contract and remaining limitations. When contracts change,
update references/examples, export affected schemas, update their provenance,
and run tests. Do not publish secrets, private previews, account IDs or real audio.

## Keep the full and compact skills aligned

`skills/pane-displays/SKILL.md` is the source of common instructions. The part
before `<!-- package-references -->` is standalone; the remaining references,
examples and helpers belong to the full GitHub package. The website uses the
same instructions as `pane`, generated as one file, and offers the complete
`pane-displays` package separately, including receiver resources. Install **one** variant per
agent, not both.

For maintainers with the application checkout (not required by installed skills):

```sh
python tools/export_compact.py --out ../epaper-system/docs/agent-skill/pane/SKILL.md
python tools/export_package.py --out ../epaper-system/docs/agent-skill/pane-displays
(
  cd ../epaper-system
  api_server/.venv/bin/python admin_dashboard/scripts/generate-docs.py
  api_server/.venv/bin/python admin_dashboard/scripts/generate-docs.py --check
)
python tools/check_application.py --app-repo ../epaper-system
python tools/check_webhook_contract.py --app-repo ../epaper-system
python -m unittest discover -s tests -v
```

These commands update local source/artifacts only, never deploy or publish.
`export_compact.py --check --out PATH` is read-only. `check_application.py` compares
the shared skill, all four bundled schemas and the reviewed public API/MCP
contract fixture with the application's current exports. When the API changes,
review the differences, copy affected public schemas, refresh their hashes/date
and the public contract fixture, then adapt behaviour/tests. Do not blindly
refresh snapshots merely to make a failed check pass. The app's own generator
must pass `--check` before comparing; stale exports cannot prove compatibility.

## License

[MIT](LICENSE) for this repository's skill materials and helper code. This does not
license the hosted Pane service, private firmware/application code, user content,
or third-party client software. Dependencies retain their own licenses.
