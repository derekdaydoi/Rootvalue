from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "content" / "knowledge.json"
ASSETS = ROOT / "assets"
ALLOWED_BLOCKS = {"heading", "paragraph", "formula", "quote", "image", "bullets"}
INDEX = ROOT / "index.html"
SERVICE_WORKER = ROOT / "sw.js"


class SiteReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.references.append(("script", str(values["src"])))
        elif tag == "link" and values.get("href"):
            self.references.append(("link", str(values["href"])))
        elif tag == "img" and values.get("src"):
            self.references.append(("image", str(values["src"])))


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def local_path(ref: str) -> Path:
    clean = ref.split("?", 1)[0].split("#", 1)[0]
    while clean.startswith("./"):
        clean = clean[2:]
    return ROOT / clean


def validate_svg(path: Path, errors: list[str]) -> None:
    try:
        ET.parse(path)
    except Exception as exc:
        fail(errors, f"Invalid SVG/XML: {path.relative_to(ROOT)}: {exc}")


def validate_image(ref: str, context: str, errors: list[str]) -> None:
    if ref.startswith(("http://", "https://", "data:")):
        return
    path = local_path(ref)
    if not path.exists():
        fail(errors, f"Missing image referenced by {context}: {ref}")
        return
    if path.stat().st_size == 0:
        fail(errors, f"Empty image referenced by {context}: {ref}")
    if path.suffix.lower() == ".svg":
        validate_svg(path, errors)


def validate_blocks(blocks: object, context: str, errors: list[str]) -> None:
    if not isinstance(blocks, list) or not blocks:
        fail(errors, f"Missing/empty content blocks: {context}")
        return
    for i, block in enumerate(blocks):
        item = f"{context}[{i}]"
        if not isinstance(block, dict):
            fail(errors, f"Block must be an object: {item}")
            continue
        kind = block.get("type")
        if kind not in ALLOWED_BLOCKS:
            fail(errors, f"Unsupported block type {kind!r}: {item}")
            continue
        if kind == "image":
            src = str(block.get("src") or "").strip()
            if not src:
                fail(errors, f"Image block has no src: {item}")
            else:
                validate_image(src, item, errors)
        elif kind == "bullets":
            values = block.get("items")
            if not isinstance(values, list) or not values:
                fail(errors, f"Bullet block has no items: {item}")
        else:
            text = str(block.get("text") or "").strip()
            if not text:
                fail(errors, f"Text block is empty: {item}")


def validate_knowledge(errors: list[str]) -> None:
    try:
        data = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(errors, f"knowledge.json is invalid JSON: {exc}")
        return

    topics = data.get("topics")
    blogs = data.get("blogs")
    if not isinstance(topics, list) or not topics:
        fail(errors, "knowledge.json must contain topics")
        topics = []
    if not isinstance(blogs, list):
        fail(errors, "knowledge.json blogs must be an array")
        blogs = []

    seen: set[str] = set()
    for item in topics:
        ident = str(item.get("id") or "").strip()
        if not ident:
            fail(errors, "Knowledge topic missing id")
            continue
        if ident in seen:
            fail(errors, f"Duplicate knowledge id: {ident}")
        seen.add(ident)
        for field in ("category_vi", "category_en", "title_vi", "title_en", "summary_vi", "summary_en"):
            if not str(item.get(field) or "").strip():
                fail(errors, f"{ident} missing {field}")
        validate_blocks(item.get("blocks_vi"), f"topic:{ident}:vi", errors)
        validate_blocks(item.get("blocks_en"), f"topic:{ident}:en", errors)

    for item in blogs:
        ident = str(item.get("id") or "").strip()
        if not ident:
            fail(errors, "Blog post missing id")
            continue
        if ident in seen:
            fail(errors, f"Duplicate content id: {ident}")
        seen.add(ident)
        for field in ("title_vi", "title_en", "excerpt_vi", "excerpt_en"):
            if not str(item.get(field) or "").strip():
                fail(errors, f"{ident} missing {field}")
        image = str(item.get("image") or "").strip()
        if image:
            validate_image(image, f"blog:{ident}", errors)
        validate_blocks(item.get("blocks_vi"), f"blog:{ident}:vi", errors)
        validate_blocks(item.get("blocks_en"), f"blog:{ident}:en", errors)


def validate_all_svgs(errors: list[str]) -> None:
    if not ASSETS.exists():
        fail(errors, "assets directory is missing")
        return
    for path in sorted(ASSETS.glob("*.svg")):
        validate_svg(path, errors)


def validate_site_shell(errors: list[str]) -> None:
    try:
        html = INDEX.read_text(encoding="utf-8")
    except Exception as exc:
        fail(errors, f"index.html cannot be read: {exc}")
        return

    parser = SiteReferenceParser()
    parser.feed(html)
    for kind, ref in parser.references:
        if ref.startswith(("http://", "https://", "data:")):
            continue
        path = local_path(ref)
        if not path.is_file():
            fail(errors, f"Missing {kind} referenced by index.html: {ref}")
        elif path.stat().st_size == 0:
            fail(errors, f"Empty {kind} referenced by index.html: {ref}")

    linked_styles = {ref.split("?", 1)[0].removeprefix("./") for kind, ref in parser.references if kind == "link"}
    if "rootvalue-v2.css" not in linked_styles:
        fail(errors, "index.html must link rootvalue-v2.css directly")

    routes = set(re.findall(r'data-route=["\']([^"\']+)', html))
    screens = set(re.findall(r'data-screen=["\']([^"\']+)', html))
    if routes != screens:
        fail(errors, f"Navigation/screen route mismatch: routes={sorted(routes)}, screens={sorted(screens)}")
    if "knowledge" not in routes:
        fail(errors, "Knowledge must be a first-class navigation route in index.html")


def validate_service_worker_shell(errors: list[str]) -> None:
    try:
        source = SERVICE_WORKER.read_text(encoding="utf-8")
    except Exception as exc:
        fail(errors, f"sw.js cannot be read: {exc}")
        return
    for ref in sorted(set(re.findall(r'["\'](\./[^"\']+)["\']', source))):
        path = local_path(ref)
        if not path.is_file():
            fail(errors, f"Service-worker shell asset missing: {ref}")


def main() -> int:
    errors: list[str] = []
    validate_knowledge(errors)
    validate_all_svgs(errors)
    validate_site_shell(errors)
    validate_service_worker_shell(errors)
    if errors:
        print("Rootvalue content QA: FAIL")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Rootvalue content QA: PASS")
    print(" - knowledge.json valid and bilingual")
    print(" - all referenced local images exist")
    print(" - all SVG assets are valid XML")
    print(" - site shell routes and local assets are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
