#!/usr/bin/env python3
"""Build a lightweight RSS feed for figure.ooo: title, top image, and article link only."""

import os
import time
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

SOURCE_FEED = os.getenv("SOURCE_FEED", "https://figure.ooo/feed.xml")
PUBLIC_FEED_URL = os.getenv("PUBLIC_FEED_URL", "")
OUTPUT = os.getenv("OUTPUT", "public/feed.xml")
UA = "Mozilla/5.0 (compatible; figureooo-rss-enhancer/1.0)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.7",
})


def get(url):
    error = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            error = exc
            time.sleep(2 ** attempt)
    raise error


def first_image_url(img, page_url):
    value = (
        img.get("src")
        or img.get("data-src")
        or img.get("data-lazy-src")
        or img.get("data-original")
    )
    if not value:
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        candidates = []
        for part in srcset.split(","):
            bits = part.strip().split()
            if bits:
                candidates.append(bits[0])
        value = candidates[-1] if candidates else ""

    if not value:
        return ""

    value = urljoin(page_url, value.strip())
    if value.startswith("data:") or urlparse(value).scheme not in ("http", "https"):
        return ""
    return value


def extract_top_image(html, page_url):
    soup = BeautifulSoup(html, "html.parser")

    # Prefer the page's explicitly designated social/share image.
    for attrs in (
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            image_url = urljoin(page_url, tag["content"].strip())
            if urlparse(image_url).scheme in ("http", "https"):
                return image_url

    # If no OG image exists, use only the first image in the article area.
    for selector in ("article", "main", ".post-content", ".entry-content"):
        body = soup.select_one(selector)
        if body:
            img = body.find("img")
            if img:
                return first_image_url(img, page_url)

    return ""


def main():
    root = ET.fromstring(get(SOURCE_FEED).content)
    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("RSS channel was not found")

    if PUBLIC_FEED_URL:
        atom_link = channel.find(f"{{{NS['atom']}}}link")
        if atom_link is None:
            atom_link = ET.SubElement(channel, f"{{{NS['atom']}}}link")
        atom_link.set("href", PUBLIC_FEED_URL)
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")

    items = channel.findall("item")
    if not items:
        raise RuntimeError("Source RSS contains no items")

    ok = failed = 0
    for number, item in enumerate(items, 1):
        link = item.findtext("link", "").strip()
        if not link:
            continue

        # Keep the source title, link, GUID, date, and categories.
        # Remove descriptions and all full-body/multiple-image payloads.
        for child in list(item):
            if child.tag in (
                "description",
                "enclosure",
                f"{{{NS['media']}}}thumbnail",
                f"{{{NS['media']}}}content",
            ) or child.tag.endswith("}encoded"):
                item.remove(child)

        try:
            response = get(link)
            image_url = extract_top_image(response.text, link)

            if image_url:
                thumb = ET.SubElement(item, f"{{{NS['media']}}}thumbnail")
                thumb.set("url", image_url)

                # A single top-image enclosure helps feed readers that do not
                # display Media RSS thumbnails. The image itself is not copied.
                enclosure = ET.SubElement(item, "enclosure")
                enclosure.set("url", image_url)
                enclosure.set("type", "image/jpeg")
                enclosure.set("length", "0")

            ok += 1
            print(f"[{number}/{len(items)}] OK top_image={'yes' if image_url else 'no'} {link}")
        except Exception as exc:
            failed += 1
            print(f"[{number}/{len(items)}] ERROR {link}: {exc}")

        # Keep requests to the source site spaced out.
        time.sleep(1)

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Completed: {ok} succeeded, {failed} failed; output={OUTPUT}")

    if ok == 0:
        raise RuntimeError("No article pages could be processed; refusing to publish an empty feed")


if __name__ == "__main__":
    main()
