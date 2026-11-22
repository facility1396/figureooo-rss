#!/usr/bin/env python3
"""Generate a minimal RSS feed from CAMELOT's official product archive.

The feed contains only product title, the card/primary image URL, and the
official product-page link. It does not copy image files or article text.
"""

import html
import json
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin, urlparse, urldefrag
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

SOURCE_URL = os.getenv("SOURCE_URL", "https://camelot-tokyo.jp/product/")
PUBLIC_FEED_URL = os.getenv("PUBLIC_FEED_URL", "")
OUTPUT = os.getenv("OUTPUT", "public/camelot/feed.xml")
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "50"))
USER_AGENT = "Mozilla/5.0 (compatible; figure-rss/1.0; +https://github.com/facility1396/figureooo-rss)"
MEDIA_NS = "http://search.yahoo.com/mrss/"
ATOM_NS = "http://www.w3.org/2005/Atom"

ET.register_namespace("media", MEDIA_NS)
ET.register_namespace("atom", ATOM_NS)

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.7",
})


def clean_text(value):
    return re.sub(r"\\s+", " ", html.unescape(value or "")).strip()


def absolute_http_url(value, base):
    if not value:
        return ""
    value = urljoin(base, value.strip())
    value, _fragment = urldefrag(value)
    if urlparse(value).scheme not in ("http", "https"):
        return ""
    return value


def image_from_tag(img, base):
    if img is None:
        return ""

    srcset = img.get("srcset") or img.get("data-srcset") or ""
    if srcset:
        choices = []
        for entry in srcset.split(","):
            parts = entry.strip().split()
            if not parts:
                continue
            score = 0
            if len(parts) > 1:
                match = re.match(r"(\\d+)(w|x)", parts[1])
                if match:
                    score = int(match.group(1))
            choices.append((score, parts[0]))
        if choices:
            return absolute_http_url(max(choices)[1], base)

    for key in ("data-src", "data-lazy-src", "data-original", "src"):
        value = img.get(key)
        if value and not value.startswith("data:"):
            return absolute_http_url(value, base)
    return ""


def product_path(url):
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path.startswith("/product/") and path != "/product"


def is_noise_link(url):
    path = urlparse(url).path.lower()
    return any(part in path for part in (
        "/page/", "/category/", "/tag/", "/feed", "/wp-json/",
        "/author/", "/cart", "/checkout",
    ))


def find_card_container(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", None) in ("article", "li"):
            return parent
        classes = " ".join(parent.get("class", [])) if getattr(parent, "get", None) else ""
        if classes and re.search(r"(product|item|card|entry)", classes, re.I):
            return parent
    return anchor.parent


def title_from_card(anchor, container):
    for node in [anchor] + list(anchor.select("h1,h2,h3,h4,.title,.name")):
        text = clean_text(node.get_text(" ", strip=True))
        if text and len(text) > 1:
            return text

    if container is not None:
        heading = container.select_one("h1,h2,h3,h4,.title,.name")
        if heading:
            text = clean_text(heading.get_text(" ", strip=True))
            if text:
                return text

    image = anchor.find("img")
    if image and image.get("alt"):
        return clean_text(image.get("alt"))
    if anchor.get("title"):
        return clean_text(anchor.get("title"))
    return ""


def date_from_card(container):
    if container is None:
        return ""
    node = container.find("time")
    if node:
        value = node.get("datetime") or node.get_text(" ", strip=True)
        return clean_text(value)
    return ""


def extract_detail_image(url):
    """Use a product page's declared primary image only when the archive has none."""
    response = session.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for attrs in (
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return absolute_http_url(tag["content"], url)

    for selector in ("main", "article", ".product", ".product-detail", ".entry-content"):
        region = soup.select_one(selector)
        if region:
            img = region.find("img")
            image_url = image_from_tag(img, url)
            if image_url:
                return image_url
    return ""


def create_feed(items, warning=""):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "CAMELOT 製品情報"
    ET.SubElement(channel, "link").text = SOURCE_URL
    description = "CAMELOT公式サイトの製品紹介ページ。タイトル・トップ画像・製品ページへのリンクのみ。"
    if warning:
        description += " 取得状況: " + warning
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "ja"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    if PUBLIC_FEED_URL:
        atom = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
        atom.set("href", PUBLIC_FEED_URL)
        atom.set("rel", "self")
        atom.set("type", "application/rss+xml")

    for entry in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry["title"]
        ET.SubElement(item, "link").text = entry["link"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = entry["link"]
        if entry.get("pub_date"):
            ET.SubElement(item, "pubDate").text = entry["pub_date"]
        if entry.get("image"):
            ET.SubElement(item, f"{{{MEDIA_NS}}}thumbnail", {"url": entry["image"]})
            mime = mimetypes.guess_type(urlparse(entry["image"]).path)[0] or "image/jpeg"
            ET.SubElement(item, "enclosure", {
                "url": entry["image"],
                "type": mime,
                "length": "0",
            })

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)


def main():
    warning = ""
    entries = []

    try:
        response = session.get(SOURCE_URL, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        page_text = soup.get_text(" ", strip=True).lower()
        if any(marker in page_text for marker in (
            "verify you are human", "checking your browser", "captcha",
            "アクセスが拒否", "人間であることを確認",
        )):
            raise RuntimeError("Bot/verification page detected; no attempt will be made to bypass it")

        found = {}
        for anchor in soup.select("a[href]"):
            link = absolute_http_url(anchor.get("href"), SOURCE_URL)
            if not link or urlparse(link).netloc != urlparse(SOURCE_URL).netloc:
                continue
            if not product_path(link) or is_noise_link(link):
                continue

            container = find_card_container(anchor)
            title = title_from_card(anchor, container)
            image = image_from_tag(anchor.find("img"), SOURCE_URL)
            if not image and container is not None:
                image = image_from_tag(container.find("img"), SOURCE_URL)

            if not title and not image:
                continue

            if link not in found:
                found[link] = {
                    "title": title,
                    "link": link,
                    "image": image,
                    "pub_date": date_from_card(container),
                }
            else:
                if not found[link]["title"] and title:
                    found[link]["title"] = title
                if not found[link]["image"] and image:
                    found[link]["image"] = image
                if not found[link]["pub_date"]:
                    found[link]["pub_date"] = date_from_card(container)

        entries = list(found.values())[:MAX_ITEMS]

        # If a listing card has no image, look for the product page's declared
        # social/primary image. Requests are spaced and capped to avoid bursts.
        missing_images = [entry for entry in entries if not entry["image"]][:12]
        for entry in missing_images:
            try:
                entry["image"] = extract_detail_image(entry["link"])
            except requests.RequestException as exc:
                print(f"WARNING: image lookup failed for {entry['link']}: {exc}")
            time.sleep(1)

        if not entries:
            warning = "商品リンクを検出できませんでした（一覧のHTML構造が未確認です）"
            print("WARNING:", warning)
        else:
            print(f"Detected {len(entries)} product links from {SOURCE_URL}")
            print(f"Items with primary image: {sum(bool(x['image']) for x in entries)}")

    except requests.RequestException as exc:
        warning = f"一覧ページを取得できませんでした: {exc}"
        print("WARNING:", warning)
    except Exception as exc:
        warning = f"一覧ページを解析できませんでした: {exc}"
        print("WARNING:", warning)

    create_feed(entries, warning)
    print(f"Wrote {len(entries)} items to {OUTPUT}")


if __name__ == "__main__":
    main()
