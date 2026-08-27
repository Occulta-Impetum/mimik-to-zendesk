#!/usr/bin/env python3
"""
Mimik HTML Converter
--------------------
Converts a Mimik HTML export into a clean article package, uploads extracted
screenshots to Zendesk Guide Media, and writes Zendesk-ready article HTML.

Usage:
    python mimik_converter.py "C:\\path\\to\\article.html"

Windows drag-and-drop:
    Drop one or more Mimik .html files onto a launcher such as:
        Convert Mimik HTML.bat

Output:
    <script directory>\\Converted Mimik HTML\\<Article Name>\\
        article-body.html
        preview.html
        manifest.json
        media-manifest.json
        conversion-summary.txt
        images\\
        source\\
            original.html
"""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: BeautifulSoup is required.")
    print("Install dependencies with:")
    print("    py -m pip install -r requirements.txt")
    input("\nPress Enter to close...")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required.")
    print("Install dependencies with:")
    print("    py -m pip install -r requirements.txt")
    input("\nPress Enter to close...")
    sys.exit(1)

try:
    from zendesk_auth import get_access_token
    from zendesk_media import upload_guide_media
except ImportError as exc:
    print("ERROR: Zendesk helper modules or dependencies could not be loaded.")
    print("Install dependencies with:")
    print("    py -m pip install -r requirements.txt")
    print(f"Details: {exc}")
    input("\nPress Enter to close...")
    sys.exit(1)


OUTPUT_ROOT_NAME = "Converted Mimik HTML"


def progress(message: str) -> None:
    """Print progress immediately so drag-and-drop BAT runs never look frozen."""
    print(message, flush=True)


def safe_folder_name(name: str) -> str:
    """Make a Windows-safe folder name while keeping it readable."""
    name = html.unescape(name).strip()
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = re.sub(r"\s+", " ", name)
    name = name.rstrip(". ")
    return name[:120] or "Untitled Mimik Article"


def get_article_title(soup: BeautifulSoup, source: Path) -> str:
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)

    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(" ", strip=True)

    return source.stem


def decode_data_image(data_uri: str, dest_png: Path) -> dict:
    """Decode a data:image URI, normalize it to PNG, and return metadata."""
    header, payload = data_uri.split(",", 1)
    mime_match = re.match(r"data:(image/[^;]+);base64", header, re.I)
    mime = mime_match.group(1).lower() if mime_match else "image/unknown"

    raw = base64.b64decode(payload)
    temp = dest_png.with_suffix(".source")
    temp.write_bytes(raw)

    try:
        with Image.open(temp) as im:
            original_format = im.format or mime.split("/")[-1].upper()
            width, height = im.size

            if im.mode not in ("RGB", "RGBA"):
                if "A" in im.getbands():
                    im = im.convert("RGBA")
                else:
                    im = im.convert("RGB")

            im.save(dest_png, "PNG", optimize=True)
    finally:
        temp.unlink(missing_ok=True)

    return {
        "original_mime": mime,
        "original_format": original_format,
        "width": width,
        "height": height,
        "output": dest_png.name,
    }


def clean_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def paragraphs_from_text(text: str) -> str:
    """Turn logical Mimik note/callout text into plain body paragraphs."""
    lines = [clean_text(x) for x in text.splitlines() if clean_text(x)]
    if not lines:
        return ""

    return "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)


def create_article_body(
    soup: BeautifulSoup,
    images_dir: Path,
    manifest: dict,
) -> str:
    """Convert Mimik's body into simple article markup with local image paths."""
    body = soup.body
    if body is None:
        raise ValueError("No <body> element was found in the Mimik HTML.")

    output = []
    image_index = 0

    sections = body.find_all("section", recursive=False)
    if not sections:
        sections = body.find_all("section")

    for section in sections:
        block = section.get("data-block")
        step_num = section.get("data-step")

        if block == "heading":
            heading = clean_text(section.get_text(" ", strip=True))
            if not heading:
                continue

            tag = "h2" if re.match(r"^\d+\.", heading) else "h3"
            output.append(f"<{tag}>{html.escape(heading)}</{tag}>")
            continue

        if block == "callout":
            text = clean_text(section.get_text("\n", strip=True))
            if text:
                output.append(paragraphs_from_text(text))
            continue

        if step_num:
            description_node = section.find("p")
            description = clean_text(
                description_node.get_text("\n", strip=True)
                if description_node
                else section.get_text("\n", strip=True)
            )

            output.append(
                f'<div class="step" data-step="{html.escape(str(step_num))}">'
            )
            output.append(
                f'<h3 class="step-title">Step {html.escape(str(step_num))}</h3>'
            )

            if description:
                desc_lines = [x for x in description.splitlines() if x.strip()]
                for line in desc_lines:
                    output.append(f"<p>{html.escape(line.strip())}</p>")

            img = section.find("img")
            if img and (img.get("src") or "").startswith("data:image"):
                image_index += 1

                if str(step_num).isdigit():
                    dest_name = f"step-{int(step_num):02d}.png"
                else:
                    dest_name = f"image-{image_index:02d}.png"

                dest_path = images_dir / dest_name
                image_meta = decode_data_image(img["src"], dest_path)
                image_meta["step"] = str(step_num)
                alt = clean_text(img.get("alt") or f"Step {step_num}")
                image_meta["alt"] = alt
                manifest["images"].append(image_meta)

                output.append(
                    f'<p class="step-image">'
                    f'<img src="images/{html.escape(dest_name)}" '
                    f'alt="{html.escape(alt)}">'
                    f"</p>"
                )

            output.append("</div>")
            continue

    if not output:
        raise ValueError(
            "No Mimik article sections were recognized. "
            "The Mimik export format may have changed."
        )

    return "\n".join(output)


def upload_images_to_zendesk(
    local_article_body: str,
    images_dir: Path,
    image_entries: list[dict],
) -> tuple[str, dict]:
    """Upload screenshots and replace local src values with Zendesk paths."""
    media_manifest = {
        "provider": "Zendesk Guide Media",
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "images": [],
    }

    if not image_entries:
        progress("[3/5] No screenshots to upload to Zendesk.")
        media_manifest["image_count"] = 0
        return local_article_body, media_manifest

    progress("[3/5] Authenticating with Zendesk...")
    auth_started = time.perf_counter()
    access_token, _ = get_access_token()
    progress(f"      Zendesk authentication succeeded ({time.perf_counter() - auth_started:.1f}s).")

    zendesk_article_body = local_article_body
    total = len(image_entries)

    progress(f"[4/5] Uploading {total} screenshot{'s' if total != 1 else ''} to Zendesk Guide Media...")

    for index, image in enumerate(image_entries, start=1):
        filename = image["output"]
        image_path = images_dir / filename
        step = image.get("step")
        step_label = f"Step {step}" if step else filename
        upload_started = time.perf_counter()

        progress(f"      [{index}/{total}] Uploading {step_label}: {filename}...")
        media = upload_guide_media(image_path, access_token, content_type="image/png")

        media_id = media["id"]
        media_url = media["url"]
        local_src = f"images/{filename}"

        old_src = f'src="{html.escape(local_src)}"'
        new_src = f'src="{html.escape(media_url)}"'

        if old_src not in zendesk_article_body:
            raise ValueError(
                f"Could not find the local image reference for {filename} "
                "in the generated article body."
            )

        zendesk_article_body = zendesk_article_body.replace(old_src, new_src, 1)

        media_manifest["images"].append(
            {
                "local_file": f"images/{filename}",
                "step": step,
                "alt": image.get("alt", ""),
                "zendesk_media_id": media_id,
                "zendesk_url": media_url,
            }
        )

        progress(
            f"            Uploaded successfully ({time.perf_counter() - upload_started:.1f}s)."
        )

    media_manifest["image_count"] = len(media_manifest["images"])
    return zendesk_article_body, media_manifest


PREVIEW_CSS = r"""
:root {
    color-scheme: light;
}

body {
    font-family: Arial, Helvetica, sans-serif;
    color: #1f2937;
    background: #ffffff;
    line-height: 1.55;
    margin: 0;
}

.article {
    max-width: 980px;
    margin: 0 auto;
    padding: 32px 28px 64px;
}

h1 {
    font-size: 2rem;
    margin: 0 0 0.5rem;
}

h2 {
    font-size: 1.45rem;
    margin: 2.25rem 0 0.75rem;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid #d1d5db;
}

h3 {
    font-size: 1.1rem;
    margin: 1.5rem 0 0.5rem;
}

p {
    margin: 0.45rem 0 0.8rem;
}

.step {
    margin: 1rem 0 2rem;
}

.step-title {
    margin-bottom: 0.35rem;
}

.step-image {
    margin-top: 0.8rem;
}

.step-image img {
    display: block;
    max-width: 100%;
    height: auto;
    border: 1px solid #d1d5db;
}

.conversion-note {
    margin-bottom: 2rem;
    padding: 0.65rem 0.8rem;
    background: #f3f4f6;
    font-size: 0.9rem;
    color: #4b5563;
}
"""


def full_preview_html(title: str, article_body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{PREVIEW_CSS}
</style>
</head>
<body>
<main class="article">
<h1>{html.escape(title)}</h1>
<div class="conversion-note">
Local preview generated from a Mimik HTML export.
Images are stored in the adjacent <strong>images</strong> folder.
</div>
{article_body}
</main>
</body>
</html>
"""


def convert_file(source: Path, script_dir: Path) -> Path:
    started = time.perf_counter()
    source = source.resolve()

    if not source.exists():
        raise FileNotFoundError(f"File does not exist: {source}")

    if source.suffix.lower() not in {".html", ".htm"}:
        raise ValueError(f"Expected an HTML file, got: {source.name}")

    progress("[1/5] Reading and parsing Mimik HTML...")
    raw_html = source.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw_html, "html.parser")
    title = get_article_title(soup, source)
    progress(f"      Article: {title}")

    output_root = script_dir / OUTPUT_ROOT_NAME
    article_dir = output_root / safe_folder_name(title)
    images_dir = article_dir / "images"
    source_dir = article_dir / "source"

    if article_dir.exists():
        progress("      Removing previous conversion of this article...")
        shutil.rmtree(article_dir)

    images_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "converter": "Mimik HTML Converter",
        "converted_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": source.name,
        "article_title": title,
        "images": [],
    }

    progress("[2/5] Cleaning article and extracting screenshots...")
    extraction_started = time.perf_counter()
    local_article_body = create_article_body(soup, images_dir, manifest)
    image_count = len(manifest["images"])
    progress(
        f"      Extracted {image_count} screenshot{'s' if image_count != 1 else ''} "
        f"({time.perf_counter() - extraction_started:.1f}s)."
    )

    zendesk_article_body, media_manifest = upload_images_to_zendesk(
        local_article_body,
        images_dir,
        manifest["images"],
    )

    progress("[5/5] Writing converted article package...")
    shutil.copy2(source, source_dir / "original.html")

    (article_dir / "article-body.html").write_text(
        zendesk_article_body,
        encoding="utf-8",
    )

    (article_dir / "preview.html").write_text(
        full_preview_html(title, local_article_body),
        encoding="utf-8",
    )

    (article_dir / "media-manifest.json").write_text(
        json.dumps(media_manifest, indent=2),
        encoding="utf-8",
    )

    manifest["image_count"] = len(manifest["images"])
    manifest["zendesk_media_count"] = media_manifest["image_count"]
    manifest["output_files"] = [
        "article-body.html",
        "preview.html",
        "manifest.json",
        "media-manifest.json",
        "conversion-summary.txt",
        "images/",
        "source/original.html",
    ]

    (article_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    summary = f"""Mimik HTML Conversion Complete

Article:
{title}

Source:
{source}

Output:
{article_dir}

Screenshots converted:
{len(manifest["images"])}

Screenshots uploaded to Zendesk Guide Media:
{media_manifest["image_count"]}

Formatting behavior:
- Mimik cover/header/footer layout removed.
- Mimik note/callout box colors removed.
- Note/callout text preserved as normal body paragraphs.
- Step descriptions and screenshot order preserved.
- Embedded screenshots converted to PNG.
- Screenshots uploaded to Zendesk Guide Media.
- article-body.html uses the Zendesk /guide-media/... image paths.
- preview.html continues to use the local PNG copies for visual review.

Files:
- preview.html
    Open this in a browser to review the cleaned article locally.

- article-body.html
    Zendesk-ready article-body fragment using Zendesk Guide Media image paths.

- images\\
    Local copies of screenshots extracted from the Mimik export and converted
    to PNG. These are retained for visual review and ChatGPT editorial cleanup.

- media-manifest.json
    Mapping between each local screenshot, its step/alt text, Zendesk media ID,
    and the Zendesk image path used by article-body.html.

- manifest.json
    Machine-readable conversion details.

- source\\original.html
    Copy of the original Mimik HTML export used for this conversion.

The original Mimik export was not modified.
"""

    (article_dir / "conversion-summary.txt").write_text(
        summary,
        encoding="utf-8",
    )

    progress(f"      Package written successfully ({time.perf_counter() - started:.1f}s total).")
    return article_dir


def main() -> int:
    script_dir = Path(__file__).resolve().parent

    if len(sys.argv) < 2:
        print("Mimik HTML Converter")
        print("--------------------")
        print("Drag one or more Mimik HTML files onto the launcher")
        print("or run:")
        print('    py mimik_converter.py "C:\\path\\to\\article.html"')
        input("\nPress Enter to close...")
        return 1

    sources = [Path(arg.strip('"')) for arg in sys.argv[1:]]
    failures = []

    print("\nMimik HTML Converter")
    print("====================\n")

    for source in sources:
        try:
            print(f"Converting: {source}", flush=True)
            output = convert_file(source, script_dir)
            print(f"Completed:  {output}\n", flush=True)
        except Exception as exc:
            failures.append((source, exc))
            print(f"FAILED: {source}", flush=True)
            print(f"Reason: {exc}\n", flush=True)

    if failures:
        print("One or more files could not be converted.")
        print("See the errors above.")
        input("\nPress Enter to close...")
        return 2

    print("All conversions completed successfully.")
    input("\nPress Enter to close...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
