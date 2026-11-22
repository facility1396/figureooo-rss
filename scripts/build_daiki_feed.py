#!/usr/bin/env python3
"""Generate a current product RSS feed from Daiki Kogyo's WordPress product archive."""

import os
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = "https://daikikougyou.com"
ARCHIVE = os.getenv("DAIKI_ARCHIVE", BASE + "/products/")
PUBLIC_URL = os.getenv("PUBLIC_FEED_URL", "https://facility1396.github.io/figureooo-rss/daiki/feed.xml")
OUTPUT = os.getenv("OUTPUT", "public/daiki/feed.xml")
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
UA = "Mozilla/5.0 (compatible; DaikiKogyoRSS/1.0)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
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
    last = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise last

def clean_text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""

def image_url(img, page_url):
    value = (
        img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        or img.get("data-original") or img.get("data-srcset", "").split(",")[-1].strip().split(" ")[0]
    )
    if not value and img.get("srcset"):
        value = img["srcset"].split(",")[-1].strip().split(" ")[0]
    if not value:
        return ""
    value = urljoin(page_url, value.strip().split(" ")[0])
    if value.startswith("data:") or urlparse(value).scheme not in ("http", "https"):
        return ""
    return value

def parse_archive_page(url):
    soup = BeautifulSoup(get(url).text, "html.parser")
    found = []
    seen = set()

    # The product archive uses WordPress post links under /products/.
    for anchor in soup.select('a[href*="/products/"]'):
        href = urljoin(url, anchor.get("href", ""))
        path = urlparse(href).path.rstrip("/")
        if not path.startswith("/products/") or path == "/products":
            continue
        if path in ("/products/page/2",) or re.search(r"/products/page/\d+$", path):
            continue
        if path in seen:
            continue
        title = clean_text(anchor)
        if not title or title in ("続きを読む", "製品一覧"):
            # Try the containing article's heading.
            parent = anchor.find_parent(["article", "li", "div"])
            heading = parent.select_one("h1,h2,h3,h4") if parent else None
            title = clean_text(heading)
        if not title:
            continue
        seen.add(path)

        parent = anchor.find_parent("article") or anchor.find_parent("li") or anchor.parent
        date_text = ""
        if parent:
            date_node = parent.select_one("time, .entry-date, .posted-on, .date")
            date_text = clean_text(date_node) or clean_text(parent)
        found.append({"url": href, "title": title, "date_text": date_text})
    return found

def parse_date(value):
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", value or "")
    if match:
        y, m, d = map(int, match.groups())
        return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)

def extract_detail(url):
    soup = BeautifulSoup(get(url).text, "html.parser")

    # Prefer WordPress post content; fall back to the main article container.
    body = None
    for selector in (
        ".entry-content", ".post-content", ".product-content",
        "article .content", "article", "main"
    ):
        candidate = soup.select_one(selector)
        if candidate and (candidate.find("img") or len(clean_text(candidate)) > 80):
            body = candidate
            break

    title_node = soup.select_one("h1.entry-title, article h1, main h1, h1")
    title = clean_text(title_node)

    og_image = ""
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            og_image = urljoin(url, meta["content"].strip())
            break

    images = []
    if body:
        for unwanted in body.select("script,style,noscript,iframe,form"):
            unwanted.decompose()
        for img in body.find_all("img"):
            src = image_url(img, url)
            if not src:
                continue
            img["src"] = src
            for attr in ("data-src", "data-lazy-src", "data-original", "srcset", "data-srcset", "loading"):
                img.attrs.pop(attr, None)
            if src not in images:
                images.append(src)

    if og_image:
        images = [og_image] + [u for u in images if u != og_image]

    body_html = str(body) if body else ""
    if og_image and (not body or not body.find("img")):
        body_html = f'<p><img src="{og_image}" alt=""></p>' + body_html

    # Use the page's visible publication date where available.
    date_text = ""
    if body:
        parent = body.find_parent("article") or body.parent
        if parent:
            date_text = clean_text(parent.select_one("time, .entry-date, .posted-on, .date"))
    if not date_text:
        date_text = clean_text(soup.select_one("time, .entry-date, .posted-on, .date"))

    description = clean_text(body)
    return title, date_text, description, images, body_html

def main():
    products = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        page_url = ARCHIVE if page == 1 else urljoin(ARCHIVE, f"page/{page}/")
        try:
            entries = parse_archive_page(page_url)
        except requests.HTTPError as exc:
            if page == 1:
                raise
            print(f"Pagination stopped at page {page}: {exc}")
            break
        if not entries:
            break
        for entry in entries:
            if entry["url"] not in seen:
                seen.add(entry["url"])
                products.append(entry)
        time.sleep(1)

    if not products:
        raise RuntimeError("No product links found on the official product archive")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "ダイキ工業 新製品RSS"
    ET.SubElement(channel, "link").text = BASE + "/products/"
    ET.SubElement(channel, "description").text = "ダイキ工業公式サイトの製品一覧から生成した新製品フィード。"
    ET.SubElement(channel, "language").text = "ja"
    atom = ET.SubElement(channel, f"{{{NS['atom']}}}link")
    atom.set("href", PUBLIC_URL)
    atom.set("rel", "self")
    atom.set("type", "application/rss+xml")
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    success = 0
    errors = 0
    for idx, entry in enumerate(products, 1):
        try:
            title, detail_date, description, images, body_html = extract_detail(entry["url"])
            title = title or entry["title"]
            date = parse_date(detail_date or entry["date_text"])

            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = title
            ET.SubElement(item, "link").text = entry["url"]
            guid = ET.SubElement(item, "guid", {"isPermaLink": "true"})
            guid.text = entry["url"]
            ET.SubElement(item, "pubDate").text = format_datetime(date)
            ET.SubElement(item, "category").text = "製品情報"
            ET.SubElement(item, "description").text = description or title

            if images:
                thumb = ET.SubElement(item, f"{{{NS['media']}}}thumbnail")
                thumb.set("url", images[0])
                for src in images:
                    media = ET.SubElement(item, f"{{{NS['media']}}}content")
                    media.set("url", src)
                    media.set("medium", "image")
                enclosure = ET.SubElement(item, "enclosure")
                enclosure.set("url", images[0])
                enclosure.set("type", "image/jpeg")
                enclosure.set("length", "0")

            if body_html:
                encoded = ET.SubElement(item, f"{{{NS['content']}}}encoded")
                encoded.text = body_html

            success += 1
            print(f"[{idx}/{len(products)}] OK images={len(images)} {entry['url']}")
        except Exception as exc:
            errors += 1
            print(f"[{idx}/{len(products)}] ERROR {entry['url']}: {exc}")
        time.sleep(1)

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Done: {success} products succeeded, {errors} failed; output={OUTPUT}")
    if success == 0:
        raise RuntimeError("No product pages could be processed")

if __name__ == "__main__":
    main()
