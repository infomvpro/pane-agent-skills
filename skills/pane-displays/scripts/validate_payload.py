"""Offline contract validation; does not render, authenticate or publish."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource

from pane_common import SafeError, emit, read_json, run_cli

ROOT = Path(__file__).resolve().parents[1]
INTEGER_PRIORITY = {"type": "integer", "minimum": 0, "maximum": 1000}
TTL = {"type": "integer", "minimum": 5, "maximum": 3600}
STRING = {"type": "string", "minLength": 1}
PUBLICATION_OPTIONS = {
    "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128,
                        "pattern": r"^[A-Za-z0-9_.:-]+$"},
    "expected_publication_version": {"type": "integer", "minimum": 0, "maximum": 2**63 - 1},
}
CARD = {
    "type": "object", "required": ["type", "data"], "additionalProperties": False,
    "properties": {
        "id": {**STRING, "maxLength": 128},
        "type": {**STRING, "pattern": r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*$", "maxLength": 128},
        "priority": INTEGER_PRIORITY, "data": {"type": "object"},
    },
}
POLICY = {"enum": ["replace_lower_priority", "replace_current", "drop_if_busy"]}
CARDS = {"type": "array", "minItems": 1, "maxItems": 24, "items": CARD}
MCP_RENDER = {
    "type": "object", "required": ["display_id", "cards"], "additionalProperties": False,
    "properties": {"display_id": STRING, "cards": CARDS, "view_mode": {"enum": ["main", "temporary"]},
                   "ttl_sec": TTL, "temporary_reason": {"type": "string"},
                   "temporary_priority": INTEGER_PRIORITY, "conflict_policy": POLICY,
                   **PUBLICATION_OPTIONS},
}
REST_RENDER = {
    "type": "object", "required": ["cards"], "additionalProperties": False,
    "properties": {
        **PUBLICATION_OPTIONS,
        "screen_id": STRING, "view_mode": {"enum": ["main", "temporary"]},
        "cards": {**CARDS, "items": {**CARD, "required": ["id", "type", "data"]}},
        "temporary_view": {
            "type": "object", "required": ["ttl_sec"], "additionalProperties": False,
            "properties": {"ttl_sec": TTL, "reason": {"type": "string"},
                           "priority": INTEGER_PRIORITY, "return_policy": {"const": "return_to_main"},
                           "conflict_policy": POLICY},
        },
    },
}
NOTIFY = {
    "type": "object", "required": ["display_id", "title", "message"], "additionalProperties": False,
    "properties": {"display_id": STRING, "title": STRING, "message": STRING, "ttl_sec": TTL,
                   "priority": INTEGER_PRIORITY, "level": {"enum": ["info", "success", "warning", "error"]},
                   **PUBLICATION_OPTIONS},
}
REST_NOTIFY = {**NOTIFY, "required": ["title", "message"],
               "properties": {k: v for k, v in NOTIFY["properties"].items() if k != "display_id"}}
MCP_PREVIEW = {**MCP_RENDER, "properties": {
    k: v for k, v in MCP_RENDER["properties"].items() if k not in PUBLICATION_OPTIONS
}}
MULTI = {"type": "object", "required": ["renders"], "additionalProperties": False,
         "properties": {"renders": {"type": "array", "minItems": 1, "maxItems": 20, "items": MCP_RENDER}}}
KINDS = {"render-mcp": MCP_RENDER, "render-rest": REST_RENDER, "preview-mcp": MCP_PREVIEW,
         "notify-mcp": NOTIFY, "notify-rest": REST_NOTIFY, "multi-display": MULTI}


def deny_retrieve(uri: str) -> Any:
    raise NoSuchResource(ref=uri)


def inspect_refs(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("$ref", "$dynamicRef") and (not isinstance(value, str) or not value.startswith("#")):
                raise SafeError("external_schema_reference_not_allowed")
            inspect_refs(value)
    elif isinstance(node, list):
        for value in node:
            inspect_refs(value)


def check(schema: dict[str, Any], data: Any, label: str) -> list[dict[str, Any]]:
    inspect_refs(schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, registry=Registry(retrieve=deny_retrieve))
    # Do not emit ValidationError.message: it can contain private card data.
    return [{"location": label, "rule": error.validator} for error in validator.iter_errors(data)]


def validate(payload: Any, kind: str, schema_dir: Path) -> dict[str, Any]:
    errors = check(KINDS[kind], payload, "envelope")
    warnings: list[dict[str, Any]] = []
    if errors:
        return {"ok": False, "errors": errors[:30], "warnings": warnings}
    renders = payload["renders"] if kind == "multi-display" else [payload]
    for ri, render in enumerate(renders):
        # JSON Schema treats 1.0 as an integer; the server's version guard is strict.
        if ("expected_publication_version" in render
                and type(render["expected_publication_version"]) is not int):
            errors.append({"location": f"render[{ri}]", "rule": "strict_publication_version_integer"})
        if ("idempotency_key" in render
                and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", render["idempotency_key"])):
            errors.append({"location": f"render[{ri}]", "rule": "invalid_idempotency_key"})
        if kind in ("notify-mcp", "notify-rest"):
            continue
        label = f"render[{ri}]"
        temporary = render.get("view_mode", "main") == "temporary"
        if kind == "render-rest" and temporary and "temporary_view" not in render:
            errors.append({"location": label, "rule": "temporary_view_required"})
        if not temporary and any(k in render for k in ("temporary_view", "ttl_sec", "temporary_reason", "temporary_priority", "conflict_policy")):
            errors.append({"location": label, "rule": "temporary_options_on_main"})
        if temporary and kind != "render-rest" and "ttl_sec" not in render:
            warnings.append({"location": label, "rule": "implicit_45_second_ttl"})
        ids = [card["id"] for card in render["cards"] if "id" in card]
        if len(ids) != len(set(ids)):
            errors.append({"location": label, "rule": "duplicate_card_id"})
        for ci, card in enumerate(render["cards"]):
            card_type = card["type"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*", card_type):
                raise SafeError("invalid_card_type")
            path = schema_dir / f"{card_type}.schema.json"
            if not path.is_file():
                errors.append({"location": f"{label}.card[{ci}]", "rule": "schema_missing_export_get_card_schema"})
                continue
            schema = read_json(path)
            if isinstance(schema, dict) and "schema_available" in schema:
                if schema.get("schema_available") is not True or schema.get("card_type") != card_type:
                    raise SafeError("schema_export_unavailable_or_wrong_card_type")
                schema = schema.get("schema")
            if not isinstance(schema, dict):
                raise SafeError("invalid_card_schema")
            clabel = f"{label}.card[{ci}]"
            errors.extend(check(schema, card["data"], clabel))
            if (schema.get("additionalProperties") is not False and schema.get("properties")
                    and set(card["data"]) - set(schema["properties"])):
                warnings.append({"location": clabel, "rule": "unknown_data_fields_review_for_typos"})
            if card_type == "raw.frame" and len(render["cards"]) != 1:
                errors.append({"location": clabel, "rule": "raw_frame_must_be_only_card"})
    return {"ok": not errors, "errors": errors[:30], "warnings": warnings[:30],
            "validation": "offline_schema_only_not_pixel_fit_or_server_acceptance"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--kind", choices=KINDS, default="render-mcp")
    parser.add_argument("--schema-dir", type=Path, default=ROOT / "schemas")
    parser.add_argument("--strict", action="store_true", help="Treat lint warnings as failures.")
    args = parser.parse_args()
    result = validate(read_json(args.payload), args.kind, args.schema_dir)
    if args.strict and result["warnings"]:
        result["ok"] = False
    emit(result)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    run_cli(main)
