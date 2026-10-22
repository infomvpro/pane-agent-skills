"""Export the shared instructions as the standalone Pane website skill."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills/pane-displays/SKILL.md"
BOUNDARY = "\n<!-- package-references -->\n"


def compact_skill(source: str) -> str:
    if source.count(BOUNDARY) != 1 or source.count("\nname: pane-displays\n") != 1:
        raise ValueError("Expected one package boundary and pane-displays frontmatter")
    core = source.split(BOUNDARY)[0].rstrip() + "\n"
    # The website ZIP contains one file; local reference links would break it.
    for target in re.findall(r"\]\(([^)]+)\)", core):
        if not target.startswith(("https://", "#")):
            raise ValueError("Common instructions must not link to package-only files")
    core = core.replace("\nname: pane-displays\n", "\nname: pane\n", 1)
    return core + "\n<!-- Generated from infomvpro/pane-agent-skills by tools/export_compact.py. -->\n"


def export(destination: Path, *, check: bool) -> bool:
    content = compact_skill(SOURCE.read_text())
    if destination.is_symlink():
        raise ValueError("Refusing a symlink destination")
    matches = destination.is_file() and destination.read_text() == content
    if check:
        return matches
    if not matches:
        destination.write_text(content)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Existing parent directory is required.")
    parser.add_argument("--check", action="store_true", help="Check without changing files.")
    args = parser.parse_args()
    if not export(args.out, check=args.check):
        print("Compact skill is out of date")
        return 1
    print("Compact skill verified" if args.check else "Compact skill exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
