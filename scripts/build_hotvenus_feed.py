#!/usr/bin/env python3
"""Build an image-enriched RSS from HOTVENUS's official Works feed.

The official RSS is the sole source of item discovery. For each linked detail
page, prefer a product-specific image embedded in the page body. Generic/shared
Open Graph images are deliberately rejected; if no trustworthy image is found,
the item is published without an image rather than with a dummy.
"""
import mimetypes
import os
import re
import time
from collections import Counter
from urllib.parse import urljoin, urlparse, urldefrag
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

SOURCE_FEED = os.getenv("SOURCE_FEED", "https://hotvenus.jp/works/feed/")
PUBLIC_FEED_URL = os.getenv(
    "PUBLIC_FEED_URL",
    "https://facility1396.github.io/figureooo-rss/hotvenus/feed.xml",
)
OUTPUT = os.getenv("OUTPUT", "public/hotvenus/feed.xml")
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "100"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1"))

ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)

GENERIC_RE = re.compile(
    r"(logo|icon|banner|sns|qr|placeholder|no[-_ ]?image|noimage|dummy|"
    r"default|loading|spacer|blank|background|avatar|share|facebook|twitter|"
    r"instagram|line[-_ ]?icon|header|footer|age[-_ ]?gate)",
    re.I,
)
CONTENT_RE = re.compile(
    r"(works|product|detail|gallery|slider|swiper|slick|visual|main|kv|"
    r"single|entry|item|photo|image)",
    re.I,
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HOTVENUS-RSS/1.1; +https://github.com/facility1396/figureooo-rss)",
    "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.7",
})


def get(url):
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_error


def absolute_image_url(value, page_url):
    if not value:
        return ""
    value = urljoin(page_url, value.strip())
    value, _fragment = urldefrag(value)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.path.lower().endswith(".svg"):
        return ""
    return value


def normalized(value):
    return re.sub(r"[^\wぁ-んァ-ヶ一-龯]", "", (value or "").casefold())


def image_from_img(img, page_url):
    """Return the largest usable URL from an img element."""
    srcset = img.get("srcset") or img.get("data-srcset") or ""
    if srcset:
        candidates = []
        for part in srcset.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            score = 0
            if len(bits) > 1:
                match = re.match(r"(\d+)(w|x)", bits[1])
                if match:
                    score = int(match.group(1))
            url = absolute_image_url(bits[0], page_url)
            if url:
                candidates.append((score, url))
        if candidates:
            return max(candidates)[1]

    for key in ("data-src", "data-lazy-src", "data-original", "src"):
        value = img.get(key)
        if value and not value.strip().startswith("data:"):
            url = absolute_image_url(value, page_url)
            if url:
                return url
    return ""


def image_identity(image_url):
    parsed = urlparse(image_url)
    # Ignore resizing/cache query parameters when detecting shared assets.
    return f"{parsed.netloc.lower()}{parsed.path}".casefold()


def extract_image_candidates(page_html, page_url, item_title):
    soup = BeautifulSoup(page_html, "html.parser")
    title_key = normalized(item_title)
    candidates = {}
    regions = []

    # Collect image-bearing content regions first. These outrank site-wide
    # social metadata, which may point to a generic placeholder.
    for selector in (
        ".p-works-detail", ".works-detail", ".works-single",
        ".single-works", ".entry-content", "article", "main",
    ):
        for region in soup.select(selector):
            if region.find("img"):
                regions.append((region, 35))

    # If a theme uses different class names, still inspect the document body,
    # but score those images lower and reject navigation/footer assets.
    if not regions and soup.body:
        regions.append((soup.body, 10))

    for region, base_score in regions:
        for img in region.find_all("img"):
            image_url = image_from_img(img, page_url)
            if not image_url:
                continue

            classes = " ".join(img.get("class", []))
            parent_classes = " ".join(
                " ".join(parent.get("class", []))
                for parent in img.parents
                if getattr(parent, "get", None) and parent.name not in ("body", "html")
            )
            alt = img.get("alt", "")
            title_attr = img.get("title", "")
            context = " ".join((image_url, classes, parent_classes, alt, title_attr))

            if GENERIC_RE.search(context):
                continue

            width = img.get("width", "")
            height = img.get("height", "")
            try:
                area = int(re.sub(r"\D", "", str(width))) * int(re.sub(r"\D", "", str(height)))
            except (TypeError, ValueError):
                area = 0
            if area and area < 40000:
                continue

            score = base_score
            if CONTENT_RE.search(classes + " " + parent_classes):
                score += 15
            if title_key and len(title_key) >= 3:
                if title_key in normalized(alt + " " + title_attr + " " + image_url):
                    score += 70
            if area >= 500000:
                score += 15
            elif area and area < 120000:
                score -= 15
            if re.search(r"[-_]\d{2,4}x\d{2,4}(?=\.)", urlparse(image_url).path):
                score -= 10

            old = candidates.get(image_url)
            if old is None or score > old:
                candidates[image_url] = score

    # OGP/Twitter metadata is only a low-priority fallback. It is accepted
    # later only when it is unique to this product and corroborated by title.
    for attrs in (
        {"property": "og:image"},
        {"property": "og:image:secure_url"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if not meta or not meta.get("content"):
            continue
        image_url = absolute_image_url(meta["content"], page_url)
        if not image_url or GENERIC_RE.search(image_url):
            continue
        corroborated = bool(
            title_key and len(title_key) >= 3
            and title_key in normalized(image_url)
        )
        score = 30 if corroborated else -20
        candidates[image_url] = max(score, candidates.get(image_url, -999))

    return sorted(
        ({"url": url, "score": score} for url, score in candidates.items()),
        key=lambda candidate: candidate["score"],
        reverse=True,
    )


def main():
    feed_response = get(SOURCE_FEED)
    try:
        root = ET.fromstring(feed_response.content)
    except ET.ParseError as exc:
        raise RuntimeError(f"HOTVENUS official feed is not valid XML: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("HOTVENUS RSS channel was not found")

    source_items = channel.findall("item")
    if not source_items:
        raise RuntimeError("HOTVENUS official RSS contains no items")

    rss = ET.Element("rss", {"version": "2.0"})
    out_channel = ET.SubElement(rss, "channel")
    ET.SubElement(out_channel, "title").text = "HOTVENUS 製品情報"
    ET.SubElement(out_channel, "link").text = "https://hotvenus.jp/works/"
    ET.SubElement(out_channel, "description").text = (
        "HOTVENUS公式WORKSの製品情報。商品タイトル・商品固有のトップ画像・商品ページへのリンクのみ。"
    )
    language = channel.findtext("language")
    if language:
        ET.SubElement(out_channel, "language").text = language
    last_build = channel.findtext("lastBuildDate", "").strip()
    if last_build:
        ET.SubElement(out_channel, "lastBuildDate").text = last_build

    atom_link = ET.SubElement(out_channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", PUBLIC_FEED_URL)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    # First pass: fetch all detail pages and gather candidate images.
    records = []
    seen = set()
    page_ok = page_errors = 0
    for index, source_item in enumerate(source_items[:MAX_ITEMS], 1):
        link = source_item.findtext("link", "").strip()
        item_title = source_item.findtext("title", "").strip()
        if not link or not item_title or link in seen:
            continue

        parsed = urlparse(link)
        if parsed.netloc.lower() not in ("hotvenus.jp", "www.hotvenus.jp"):
            print(f"[{index}] SKIP external/non-HOTVENUS link: {link}")
            continue

        seen.add(link)
        candidates = []
        try:
            response = get(link)
            candidates = extract_image_candidates(response.text, response.url, item_title)
            page_ok += 1
            print(
                f"[{index}/{len(source_items)}] FETCHED candidates={len(candidates)} {link}"
            )
        except requests.RequestException as exc:
            page_errors += 1
            print(f"[{index}/{len(source_items)}] ERROR {link}: {exc}")

        records.append({
            "source_item": source_item,
            "title": item_title,
            "link": link,
            "candidates": candidates,
        })
        time.sleep(REQUEST_DELAY)

    if not records:
        raise RuntimeError("No valid HOTVENUS Works items were found in the official feed")

    # Count candidate URLs across different products. Shared assets (including
    # generic OG images that happen to have unusual filenames) are rejected.
    frequency = Counter()
    for record in records:
        identities = {
            image_identity(candidate["url"])
            for candidate in record["candidates"]
            if candidate["score"] >= 20
        }
        frequency.update(identities)

    no_image = 0
    for record in records:
        selected = ""
        for candidate in record["candidates"]:
            if candidate["score"] < 20:
                continue
            if frequency[image_identity(candidate["url"])] != 1:
                continue
            selected = candidate["url"]
            break

        if selected:
            print(f"SELECTED image=yes title={record['title']} url={selected}")
        else:
            no_image += 1
            print(f"WARNING image=not-found-or-untrusted title={record['title']}")

        out_item = ET.SubElement(out_channel, "item")
        ET.SubElement(out_item, "title").text = record["title"]
        ET.SubElement(out_item, "link").text = record["link"]

        source_item = record["source_item"]
        guid = source_item.find("guid")
        guid_value = (guid.text or "").strip() if guid is not None else record["link"]
        guid_attrs = (
            {"isPermaLink": guid.get("isPermaLink", "true")}
            if guid is not None else {"isPermaLink": "true"}
        )
        ET.SubElement(out_item, "guid", guid_attrs).text = guid_value

        pub_date = source_item.findtext("pubDate", "").strip()
        if pub_date:
            ET.SubElement(out_item, "pubDate").text = pub_date

        if selected:
            ET.SubElement(out_item, f"{{{MEDIA_NS}}}thumbnail", {"url": selected})
            image_type = mimetypes.guess_type(urlparse(selected).path)[0] or "image/jpeg"
            ET.SubElement(out_item, "enclosure", {
                "url": selected,
                "type": image_type,
                "length": "0",
            })

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(
        f"HOTVENUS complete: items={len(records)}, pages_ok={page_ok}, "
        f"page_errors={page_errors}, images_missing_or_rejected={no_image}, "
        f"output={OUTPUT}"
    )


if __name__ == "__main__":
    main()
