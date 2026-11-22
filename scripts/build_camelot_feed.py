#!/usr/bin/env python3
"""Build a minimal CAMELOT product RSS feed.

Live product cards are preferred. If the site returns a page with no detectable
cards or an HTTP/network error, use the last inspected HTML snapshot data.
This preserves a non-empty feed without attempting to bypass site protections.
"""
import json
import mimetypes
import os
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

SOURCE_URL = os.getenv("SOURCE_URL", "https://camelot-tokyo.jp/product/")
PUBLIC_FEED_URL = os.getenv("PUBLIC_FEED_URL", "https://facility1396.github.io/figureooo-rss/camelot/feed.xml")
OUTPUT = os.getenv("OUTPUT", "public/camelot/feed.xml")
FALLBACK_JSON = os.getenv("FALLBACK_JSON", "data/camelot_fallback.json")
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "100"))

ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; figureooo-rss-enhancer/1.0)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.7",
})


def absolute_http_url(value):
    if not value:
        return ""
    value = urljoin(SOURCE_URL, value.strip())
    value, _fragment = urldefrag(value)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.netloc.lower() not in ("camelot-tokyo.jp", "www.camelot-tokyo.jp"):
        return ""
    return value


def get_source_page():
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(SOURCE_URL, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_error


def extract_products(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    cards = soup.select("article.p-product-card")
    products = []
    seen = set()
    skipped_without_link = 0

    for card in cards:
        anchor = card.select_one("a.p-product-card__link[href]")
        if anchor is None:
            skipped_without_link += 1
            continue

        link = absolute_http_url(anchor.get("href"))
        title_node = card.select_one(".p-product-card__title")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        image_node = card.select_one("img.p-product-card__image")
        image = ""
        if image_node:
            for key in ("src", "data-src", "data-lazy-src", "data-original"):
                candidate = image_node.get(key)
                if candidate and not candidate.strip().startswith("data:"):
                    image = absolute_http_url(candidate)
                    if image:
                        break
            if not image:
                srcset = image_node.get("srcset") or image_node.get("data-srcset") or ""
                candidates = []
                for part in srcset.split(","):
                    bits = part.strip().split()
                    if not bits:
                        continue
                    width = 0
                    if len(bits) > 1 and bits[1].endswith("w"):
                        try:
                            width = int(bits[1][:-1])
                        except ValueError:
                            pass
                    candidate = absolute_http_url(bits[0])
                    if candidate:
                        candidates.append((width, candidate))
                if candidates:
                    image = max(candidates)[1]

        if not link or not title or link in seen:
            continue
        if not urlparse(link).path.startswith("/product/"):
            continue

        seen.add(link)
        products.append({"title": title, "link": link, "image": image})
        if len(products) >= MAX_ITEMS:
            break

    page_title = soup.title.get_text(" ", strip=True) if soup.title else "(no title)"
    print(
        f"Live source diagnostics: status=200 final_url={SOURCE_URL} "
        f"html_bytes={len(page_html.encode('utf-8'))} title={page_title!r}"
    )
    print(
        f"Live parse: found {len(cards)} product cards; "
        f"skipped {skipped_without_link} cards without links; "
        f"emitting {len(products)} linked products."
    )
    return products, len(cards)


def load_fallback():
    if not os.path.exists(FALLBACK_JSON):
        raise RuntimeError(f"Fallback snapshot not found: {FALLBACK_JSON}")
    with open(FALLBACK_JSON, "r", encoding="utf-8") as file:
        raw_items = json.load(file)

    products = []
    for item in raw_items:
        title = str(item.get("title", "")).strip()
        link = absolute_http_url(item.get("link", ""))
        image = absolute_http_url(item.get("image", ""))
        if title and link and urlparse(link).path.startswith("/product/"):
            products.append({"title": title, "link": link, "image": image})

    if not products:
        raise RuntimeError("Fallback snapshot contains no valid linked CAMELOT products")
    print(
        f"WARNING: live CAMELOT page could not be parsed; "
        f"using {len(products)} products from {FALLBACK_JSON}. "
        "This snapshot may be stale until live retrieval works again."
    )
    return products[:MAX_ITEMS]


def build_feed(products):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "CAMELOT Tokyo 製品情報"
    ET.SubElement(channel, "link").text = SOURCE_URL
    ET.SubElement(channel, "description").text = (
        "CAMELOT公式製品一覧から、商品タイトル・トップ画像・商品ページへのリンクを掲載します。"
    )
    ET.SubElement(channel, "language").text = "ja"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    self_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
    self_link.set("href", PUBLIC_FEED_URL)
    self_link.set("rel", "self")
    self_link.set("type", "application/rss+xml")

    for product in products:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = product["title"]
        ET.SubElement(item, "link").text = product["link"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = product["link"]

        image = product["image"]
        if image:
            ET.SubElement(item, f"{{{MEDIA_NS}}}thumbnail", {"url": image})
            ET.SubElement(item, "enclosure", {
                "url": image,
                "type": mimetypes.guess_type(urlparse(image).path)[0] or "image/jpeg",
                "length": "0",
            })
    return rss


def main():
    products = []
    try:
        response = get_source_page()
        products, card_count = extract_products(response.text)
        if not products:
            print(
                f"Live page returned {card_count} cards but no linked products; "
                "falling back to the inspected snapshot."
            )
    except requests.RequestException as exc:
        print(f"WARNING: live CAMELOT request failed: {exc}")

    if not products:
        products = load_fallback()

    rss = build_feed(products)
    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(products)} CAMELOT products to {OUTPUT}")


if __name__ == "__main__":
    main()
