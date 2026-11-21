#!/usr/bin/env python3
"""Build an image-enriched RSS feed from figure.ooo."""

import os
import re
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
    "content": "http://purl.org/rss/1.0/modules/content/",
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

def srcset_largest(value):
    candidates = []
    for part in (value or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        score = 0
        if len(bits) > 1:
            match = re.match(r"([\d.]+)(w|x)", bits[1])
            if match:
                score = float(match.group(1)) * (10000 if match.group(2) == "w" else 1)
        candidates.append((score, bits[0]))
    return max(candidates)[1] if candidates else ""

def absolute_image_url(img, page_url):
    value = (
        img.get("src")
        or img.get("data-src")
        or img.get("data-lazy-src")
        or img.get("data-original")
        or srcset_largest(img.get("srcset"))
        or srcset_largest(img.get("data-srcset"))
    )
    if not value:
        return ""
    value = urljoin(page_url, value.strip())
    if value.startswith("data:") or urlparse(value).scheme not in ("http", "https"):
        return ""
    return value

def extract_page(html, page_url):
    soup = BeautifulSoup(html, "html.parser")

    # Jekyll article layouts commonly place the article in main/article.
    body = None
    for selector in (
        "article .post-content", "article .entry-content",
        ".post-content", ".entry-content", ".article-content",
        "article", "main"
    ):
        candidate = soup.select_one(selector)
        if candidate and (candidate.find("img") or len(candidate.get_text(" ", strip=True)) > 100):
            body = candidate
            break

    og_image = ""
    for attrs in (
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            og_image = urljoin(page_url, tag["content"].strip())
            break

    images = []
    if body:
        for unwanted in body.select("script,style,noscript,nav,footer,form,iframe"):
            unwanted.decompose()
        for img in body.find_all("img"):
            src = absolute_image_url(img, page_url)
            if not src:
                continue
            img["src"] = src
            for attr in ("data-src", "data-lazy-src", "data-original",
                         "data-srcset", "srcset", "loading"):
                img.attrs.pop(attr, None)
            if src not in images:
                images.append(src)

    # The OG image is the preferred article-list thumbnail.
    if og_image:
        images = [og_image] + [u for u in images if u != og_image]

    # If article content markup wasn't detected, still preserve a main image.
    if body:
        body_html = str(body)
    else:
        body_html = ""

    if og_image and (not body or not body.find("img")):
        body_html = f'<p><img src="{og_image}" alt=""></p>' + body_html

    return images, body_html

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

        for child in list(item):
            if child.tag in (
                f"{{{NS['content']}}}encoded",
                f"{{{NS['media']}}}thumbnail",
                f"{{{NS['media']}}}content",
            ):
                item.remove(child)

        try:
            response = get(link)
            images, body_html = extract_page(response.text, link)

            if images:
                thumb = ET.SubElement(item, f"{{{NS['media']}}}thumbnail")
                thumb.set("url", images[0])

                for image_url in images:
                    media = ET.SubElement(item, f"{{{NS['media']}}}content")
                    media.set("url", image_url)
                    media.set("medium", "image")

                # RSS enclosure is an additional hint for feed readers.
                enclosure = item.find("enclosure")
                if enclosure is None:
                    enclosure = ET.SubElement(item, "enclosure")
                enclosure.set("url", images[0])
                enclosure.set("type", "image/jpeg")
                enclosure.set("length", "0")

            if body_html:
                encoded = ET.SubElement(item, f"{{{NS['content']}}}encoded")
                encoded.text = body_html

            ok += 1
            print(f"[{number}/{len(items)}] OK images={len(images)} {link}")
        except Exception as exc:
            failed += 1
            print(f"[{number}/{len(items)}] ERROR {link}: {exc}")

        # Be polite to the origin site.
        time.sleep(1)

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Completed: {ok} succeeded, {failed} failed; output={OUTPUT}")

    if ok == 0:
        raise RuntimeError("No article pages could be processed; refusing to publish an empty feed")

if __name__ == "__main__":
    main()
