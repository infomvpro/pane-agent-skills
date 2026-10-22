"""Save existing signed PNG previews and a contact sheet; never render or publish."""
from __future__ import annotations

import argparse
import io
import os
import re
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from PIL import Image, ImageDraw, UnidentifiedImageError

from pane_common import DEFAULT_API, SafeError, api_origin, emit, get_bytes, read_json, run_cli

MAX_PIXELS = 8_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def preview_url(value: Any, origin: str) -> str:
    if not isinstance(value, str) or len(value) > 8192 or any(c.isspace() for c in value):
        raise SafeError("invalid_preview_url")
    parsed = urlsplit(value)
    path_ok = re.fullmatch(r"/(?:frames/frm_[A-Za-z0-9_-]{1,64}|render-jobs/job_[A-Za-z0-9_-]{1,64})/preview\.png", parsed.path)
    if (f"{parsed.scheme}://{parsed.netloc}" != origin or parsed.fragment or not path_ok
            or parsed.username or parsed.password):
        raise SafeError("preview_url_not_allowed")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if len(query) != 1 or query[0][0] != "access" or not query[0][1]:
        raise SafeError("signed_preview_access_required")
    return value


def png_image(raw: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format != "PNG" or im.width * im.height > MAX_PIXELS or getattr(im, "n_frames", 1) != 1:
                    raise SafeError("unsupported_preview_image")
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                rgba = im.convert("RGBA")
                result = Image.new("RGB", rgba.size, "white")
                result.paste(rgba, mask=rgba.getchannel("A"))
                return result
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise SafeError("invalid_png") from exc


def bundle(data: Any, out: Path, origin: str, fetch: Any = get_bytes) -> dict[str, Any]:
    items = data if isinstance(data, list) else [data]
    if not 1 <= len(items) <= 12 or any(not isinstance(item, dict) for item in items):
        raise SafeError("expected_one_to_twelve_preview_results")
    urls = [preview_url(item.get("preview_png_url"), origin) for item in items]
    try:
        out.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise SafeError("output_must_be_new_directory_with_existing_parent") from exc
    rows = (len(items) + 2) // 3
    sheet = Image.new("RGB", (960, rows * 260), "#f3f2ec")
    draw = ImageDraw.Draw(sheet)
    manifest: list[dict[str, Any]] = []
    for index, url in enumerate(urls):
        raw = fetch(url, timeout=15, limit=8 * 1024 * 1024)
        picture = png_image(raw)
        filename = f"preview-{index + 1:02d}.png"
        # Originals retain exact bytes; no signed URL or content JSON in manifest.
        with (out / filename).open("xb") as handle:
            os.chmod(handle.name, 0o600)
            handle.write(raw)
        manifest.append({"index": index + 1, "file": filename, "width": picture.width, "height": picture.height})
        picture.thumbnail((300, 220))
        x, y = index % 3 * 320, index // 3 * 260
        sheet.paste(picture, (x + (320 - picture.width) // 2, y + 10))
        draw.text((x + 10, y + 238), f"Preview {index + 1}", fill="black")
    sheet.save(out / "contact-sheet.png")
    os.chmod(out / "contact-sheet.png", 0o600)
    import json
    with (out / "manifest.json").open("x") as handle:
        os.chmod(handle.name, 0o600)
        json.dump({"complete": True, "previews": manifest}, handle, indent=2)
    return {"ok": True, "saved": len(manifest), "contact_sheet": "contact-sheet.png"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("responses", type=Path, help="Saved preview tool result object or array of results.")
    parser.add_argument("--out", type=Path, required=True, help="New private directory; parent must exist.")
    parser.add_argument("--api-base", default=DEFAULT_API)
    parser.add_argument("--allow-http-localhost", action="store_true", help="Local tests only.")
    args = parser.parse_args()
    origin = api_origin(args.api_base, args.allow_http_localhost)
    emit(bundle(read_json(args.responses), args.out, origin))
    return 0


if __name__ == "__main__":
    run_cli(main)
