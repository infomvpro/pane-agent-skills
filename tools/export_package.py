"""Export the complete public skill for the website; no deployment or Git changes."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/pane-displays'
FOLDERS = {'agents', 'examples', 'references', 'schemas', 'scripts'}
ROOT_FILES = {'SKILL.md', 'LICENSE', 'requirements.txt'}
EXTENSIONS = {'.md', '.py', '.json', '.yaml', '.txt'}


def package_files(source: Path = SOURCE) -> dict[str, bytes]:
    files = {}
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if '__pycache__' in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError('Package symlinks are not allowed')
        if not path.is_file():
            continue
        allowed = (len(relative.parts) == 1 and path.name in ROOT_FILES) or (
            len(relative.parts) > 1 and relative.parts[0] in FOLDERS and path.suffix in EXTENSIONS)
        if not allowed:
            raise ValueError('Unexpected package file: ' + str(relative))
        files[relative.as_posix()] = path.read_bytes()
    return files


def export(destination: Path, *, check: bool) -> bool:
    if destination.is_symlink() or destination.resolve() == SOURCE.resolve():
        raise ValueError('Invalid export destination')
    expected = package_files()
    current = package_files(destination) if destination.exists() else {}
    if check:
        return expected == current
    # Generated destination is owned by this exporter. Refuse unexpected files
    # instead of deleting them. Maintainers edit SOURCE, not the exported copy.
    extras = set(current) - set(expected)
    if extras:
        raise ValueError('Unexpected destination files; review before export')
    for name, content in expected.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not export(args.out, check=args.check):
        print('Full skill package is out of date')
        return 1
    print('Full skill package verified' if args.check else 'Full skill package exported')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
