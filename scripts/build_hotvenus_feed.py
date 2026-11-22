#!/usr/bin/env python3
"""Add one primary product image to HOTVENUS's official Works RSS.

The official RSS remains the source of product discovery. This script only
visits each linked Works detail page to find its Open Graph/primary image.
It publishes title, link, GUID/date metadata, and one image reference.
"""
import mimetypes
import os
import re
import time
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

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HOTVENUS-RSS/1.0; +https://github.com/facility1396/figureooo-rss)",
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
    return value


def image_from_img(img, page_url):
    if img is None:
        return ""

    # Prefer the largest candidate when a responsive srcset is present.
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


def extract_primary_image(page_html, page_url):
    soup = BeautifulSoup(page_html, "html.parser")

    # Open Graph is the preferred source for the page's designated lead image.
    for attrs in (
        {"property": "og:image"},
        {"property": "og:image:secure_url"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            image_url = absolute_image_url(meta["content"], page_url)
            if image_url:
                return image_url

    # Fallback: only inspect the first image in a likely product-detail region.
    selectors = (
        ".p-works-detail",
        ".works-detail",
        ".works-single",
        ".entry-content",
        "article",
        "main",
    )
    for selector in selectors:
        region = soup.select_one(selector)
        if not region:
            continue
        for img in region.find_all("img"):
            classes = " ".join(img.get("class", []))
            alt = img.get("alt", "")
            src = " ".join(str(img.get(k, "")) for k in ("src", "data-src", "data-lazy-src"))
            if re.search(r"(logo|icon|banner|sns|qr)", f"{classes} {alt} {src}", re.I):
                continue
            image_url = image_from_img(img, page_url)
            if image_url:
                return image_url

    return ""


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

    # Keep the official feed's title and original source URL, but use our own
    # public feed URL as the Atom self link.
    title = channel.findtext("title", "HOTVENUS 製品情報").strip()
    rss = ET.Element("rss", {"version": "2.0"})
    out_channel = ET.SubElement(rss, "channel")
    ET.SubElement(out_channel, "title").text = "HOTVENUS 製品情報"
    ET.SubElement(out_channel, "link").text = "https://hotvenus.jp/works/"
    ET.SubElement(out_channel, "description").text = (
        "HOTVENUS公式WORKSの製品情報。商品タイトル・トップ画像・商品ページへのリンクのみ。"
    )
    language = channel.findtext("language")
    if language:
        ET.SubElement(out_channel, "language").text = language
    ET.SubElement(out_channel, "lastBuildDate").text = channel.findtext("lastBuildDate", "")

    atom_link = ET.SubElement(out_channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", PUBLIC_FEED_URL)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    success = failed = no_image = 0
    seen = set()
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
        image_url = ""
        try:
            response = get(link)
            image_url = extract_primary_image(response.text, response.url)
            success += 1
            if image_url:
                print(f"[{index}/{len(source_items)}] OK image=yes {link}")
            else:
                no_image += 1
                print(f"[{index}/{len(source_items)}] WARNING image=not-found {link}")
        except requests.RequestException as exc:
            failed += 1
            print(f"[{index}/{len(source_items)}] ERROR {link}: {exc}")

        out_item = ET.SubElement(out_channel, "item")
        ET.SubElement(out_item, "title").text = item_title
        ET.SubElement(out_item, "link").text = link

        guid = source_item.find("guid")
        guid_value = (guid.text or "").strip() if guid is not None else link
        guid_attrs = {"isPermaLink": guid.get("isPermaLink", "true")} if guid is not None else {"isPermaLink": "true"}
        ET.SubElement(out_item, "guid", guid_attrs).text = guid_value

        pub_date = source_item.findtext("pubDate", "").strip()
        if pub_date:
            ET.SubElement(out_item, "pubDate").text = pub_date

        if image_url:
            ET.SubElement(out_item, f"{{{MEDIA_NS}}}thumbnail", {"url": image_url})
            image_type = mimetypes.guess_type(urlparse(image_url).path)[0] or "image/jpeg"
            ET.SubElement(out_item, "enclosure", {
                "url": image_url,
                "type": image_type,
                "length": "0",
            })

        time.sleep(REQUEST_DELAY)

    if not seen:
        raise RuntimeError("No valid HOTVENUS Works items were found in the official feed")

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(
        f"HOTVENUS complete: items={len(seen)}, pages_ok={success}, "
        f"page_errors={failed}, images_missing={no_image}, output={OUTPUT}"
    )


if __name__ == "__main__":
    main()
