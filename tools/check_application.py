"""Read-only comparison with an explicit local Pane application checkout.

Run the application's generate-docs.py --check first. No database, credentials,
network, private application imports or package installation are used here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from export_compact import ROOT, SOURCE, compact_skill
from export_package import package_files

TOOL_NAMES = (
    "render_display_content", "preview_display_content", "send_temporary_notification",
    "get_publication_operation", "get_frame_content",
)


def contract_from_application(app: Path) -> dict:
    public = app / "admin_dashboard/public/pane/docs"
    tools = json.loads((public / "mcp-tools.json").read_text())["tools"]
    all_schemas = json.loads((public / "openapi.json").read_text())["components"]["schemas"]
    selected = {}

    def collect(name: str) -> None:
        if name in selected:
            return
        selected[name] = all_schemas[name]

        def refs(node: object) -> None:
            if isinstance(node, dict):
                ref = node.get("$ref")
                if ref:
                    prefix = "#/components/schemas/"
                    if not ref.startswith(prefix):
                        raise ValueError("Unexpected non-local schema reference")
                    collect(ref.removeprefix(prefix))
                for value in node.values():
                    refs(value)
            elif isinstance(node, list):
                for value in node:
                    refs(value)

        refs(selected[name])

    for name in ("RenderRequest", "NotifyRequest", "FrameContent"):
        collect(name)
    found = {tool["name"]: tool["inputSchema"] for tool in tools if tool["name"] in TOOL_NAMES}
    if set(found) != set(TOOL_NAMES):
        raise ValueError("Application is missing a required tool")
    return {"mcp": found, "components": {"schemas": selected}}


def differences(app: Path) -> list[str]:
    failures = []
    compact = app / "docs/agent-skill/pane/SKILL.md"
    if not compact.is_file() or compact.read_text() != compact_skill(SOURCE.read_text()):
        failures.append("compact skill")
    full = app / "docs/agent-skill/pane-displays"
    if not full.is_dir() or package_files(full) != package_files():
        failures.append("full skill package")
    schemas = ROOT / "skills/pane-displays/schemas"
    for path in sorted(schemas.glob("*.schema.json")):
        other = app / "api_server/app/schemas-json/card-data" / path.name
        if not other.is_file() or path.read_bytes() != other.read_bytes():
            failures.append(path.name)
    snapshot = json.loads((ROOT / "tests/fixtures/public-contract.json").read_text())["contract"]
    if snapshot != contract_from_application(app):
        failures.append("public API/MCP contract snapshot")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-repo", required=True, type=Path)
    args = parser.parse_args()
    failures = differences(args.app_repo.resolve())
    if failures:
        print("Drift detected: " + ", ".join(failures))
        return 1
    print("Application matches: common instructions, full package, four card schemas, public API/MCP contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
