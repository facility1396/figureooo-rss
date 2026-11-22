#!/usr/bin/env python3
"""Build a minimal RSS feed from CAMELOT's public product archive.

Only linked product cards are emitted. Upcoming cards without a product-page
URL are intentionally skipped until CAMELOT publishes their detail pages.
Images are referenced by URL; no image files are copied.
"""

import mimetypes
import os
import time
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

SOURCE_URL = os.getenv("SOURCE_URL", "https://camelot-tokyo.jp/product/")
PUBLIC_FEED_URL = os.getenv("PUBLIC_FEED_URL", "")
OUTPUT = os.getenv("OUTPUT", "public/camelot/feed.xml")
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "100"))
USER_AGENT = "Mozilla/5.0 (compatible; figureooo-rss-enhancer/1.0)"

ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.7",
})


def get_source_page():
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(SOURCE_URL, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_error


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


def image_url_from_card(card):
    image = card.select_one("img.p-product-card__image")
    if image is None:
        return ""

    for key in ("src", "data-src", "data-lazy-src", "data-original"):
        value = image.get(key)
        if value and not value.strip().startswith("data:"):
            result = absolute_http_url(value)
            if result:
                return result

    # Responsive-image fallback: use the largest declared candidate.
    srcset = image.get("srcset") or image.get("data-srcset") or ""
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
        result = absolute_http_url(bits[0])
        if result:
            candidates.append((width, result))
    return max(candidates)[1] if candidates else ""


def extract_products(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    cards = soup.select("article.p-product-card")
    products = []
    seen = set()
    skipped_without_link = 0

    for card in cards:
        anchor = card.select_one("a.p-product-card__link[href]")
        if anchor is None:
            # The archive currently renders upcoming cards without detail URLs.
            skipped_without_link += 1
            continue

        link = absolute_http_url(anchor.get("href"))
        title_node = card.select_one(".p-product-card__title")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        image = image_url_from_card(card)

        if not link or not title or link in seen:
            continue
        if not urlparse(link).path.startswith("/product/"):
            continue

        seen.add(link)
        products.append({
            "title": title,
            "link": link,
            "image": image,
        })

        if len(products) >= MAX_ITEMS:
            break

    print(
        f"Found {len(cards)} product cards; "
        f"skipped {skipped_without_link} cards without product links; "
        f"emitting {len(products)} linked products."
    )
    return products


def build_feed(products):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "CAMELOT Tokyo 製品情報"
    ET.SubElement(channel, "link").text = SOURCE_URL
    ET.SubElement(channel, "description").text = (
        "CAMELOT公式製品一覧から、商品タイトル・トップ画像・商品ページへのリンクを掲載します。"
    )
    ET.SubElement(channel, "language").text = "ja"

    if PUBLIC_FEED_URL:
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
            thumbnail = ET.SubElement(item, f"{{{MEDIA_NS}}}thumbnail")
            thumbnail.set("url", image)

            enclosure = ET.SubElement(item, "enclosure")
            enclosure.set("url", image)
            enclosure.set("type", mimetypes.guess_type(urlparse(image).path)[0] or "image/jpeg")
            enclosure.set("length", "0")

    return rss


def main():
    page_html = get_source_page()
    products = extract_products(page_html)

    # Do not overwrite a previously published feed with an empty feed if the
    # source layout changes or the site returns an unexpected page.
    if not products:
        raise RuntimeError(
            "No linked CAMELOT product cards found; refusing to generate an empty feed."
        )

    rss = build_feed(products)
    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(products)} CAMELOT products to {OUTPUT}")


if __name__ == "__main__":
    main()
