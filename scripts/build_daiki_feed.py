#!/usr/bin/env python3
"""Build an image-rich RSS feed for Daiki Kogyo product announcements only."""

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
PUBLIC_URL = os.getenv(
    "PUBLIC_FEED_URL",
    "https://facility1396.github.io/figureooo-rss/daiki/feed.xml",
)
OUTPUT = os.getenv("OUTPUT", "public/daiki/feed.xml")
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
UA = "Mozilla/5.0 (compatible; DaikiKogyoRSS/1.0)"

# Only the official product archive is included. News and shipping notices are excluded.
ARCHIVES = [
    ("/products/", "製品情報"),
]

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

def text_of(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""

def get_image_url(img, page_url):
    value = (
        img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        or img.get("data-original")
    )
    if not value:
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        candidates = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        value = candidates[-1] if candidates else ""
    if not value:
        return ""
    value = urljoin(page_url, value.strip())
    if value.startswith("data:") or urlparse(value).scheme not in ("http", "https"):
        return ""
    return value

def parse_japanese_date(value):
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", value or "")
    if match:
        year, month, day = map(int, match.groups())
        return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)
    return None

def parse_date(value):
    if not value:
        return None
    value = value.strip()
    jp = parse_japanese_date(value)
    if jp:
        return jp
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None

def archive_entries(path, category):
    entries = []
    seen = set()
    archive_url = urljoin(BASE, path)
    for page in range(1, MAX_PAGES + 1):
        page_url = archive_url if page == 1 else urljoin(archive_url, f"page/{page}/")
        try:
            soup = BeautifulSoup(get(page_url).text, "html.parser")
        except requests.HTTPError as exc:
            if page == 1:
                raise
            print(f"Pagination ended for {path} at page {page}: {exc}")
            break

        page_entries = 0
        # Headings are used first to avoid "続きを読む" links and pagination links.
        anchors = soup.select("h1 a, h2 a, h3 a, h4 a, h5 a")
        if not anchors:
            anchors = soup.select("article a[href], .entry a[href], .post a[href]")

        for anchor in anchors:
            href = urljoin(page_url, anchor.get("href", ""))
            parsed_path = urlparse(href).path.rstrip("/") + "/"
            root_path = path.rstrip("/") + "/"
            if not parsed_path.startswith(root_path) or parsed_path == root_path:
                continue
            if re.search(r"/page/\d+/$", parsed_path):
                continue
            title = text_of(anchor)
            if not title or title in ("続きを読む", "一覧", "製品一覧"):
                continue
            if href in seen:
                continue

            container = anchor.find_parent(["article", "li"])
            if container is None:
                container = anchor.find_parent("div")
            date_node = container.select_one("time, .entry-date, .posted-on, .date") if container else None
            date_text = ""
            if date_node:
                date_text = date_node.get("datetime") or text_of(date_node)
            if not date_text and container:
                date_text = text_of(container)
            entries.append({
                "url": href,
                "title": title,
                "category": category,
                "date": parse_date(date_text),
            })
            seen.add(href)
            page_entries += 1

        print(f"{path} page {page}: found {page_entries} entries")
        if page_entries == 0:
            break
        time.sleep(1)
    return entries

def extract_detail(url):
    soup = BeautifulSoup(get(url).text, "html.parser")
    body = None
    for selector in (
        ".entry-content", ".post-content", ".product-content",
        "article .content", "article", "main"
    ):
        candidate = soup.select_one(selector)
        if candidate and (candidate.find("img") or len(text_of(candidate)) > 60):
            body = candidate
            break

    title_node = soup.select_one("h1.entry-title, article h1, main h1, h1")
    title = text_of(title_node)

    published = None
    for attrs in (
        {"property": "article:published_time"},
        {"name": "article:published_time"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            published = parse_date(meta["content"])
            if published:
                break
    if not published:
        date_node = soup.select_one("time, .entry-date, .posted-on, .date")
        if date_node:
            published = parse_date(date_node.get("datetime") or text_of(date_node))

    og_image = ""
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            og_image = urljoin(url, meta["content"].strip())
            break

    images = []
    if body:
        for unwanted in body.select("script, style, noscript, iframe, form"):
            unwanted.decompose()
        for img in body.find_all("img"):
            src = get_image_url(img, url)
            if not src:
                continue
            img["src"] = src
            for attr in (
                "data-src", "data-lazy-src", "data-original", "srcset",
                "data-srcset", "loading"
            ):
                img.attrs.pop(attr, None)
            if src not in images:
                images.append(src)

    if og_image:
        images = [og_image] + [src for src in images if src != og_image]

    body_html = str(body) if body else ""
    if og_image and (not body or not body.find("img")):
        body_html = f'<p><img src="{og_image}" alt=""></p>' + body_html

    description = text_of(body)
    return title, published, description, images, body_html

def main():
    entries = []
    for path, category in ARCHIVES:
        try:
            found = archive_entries(path, category)
            entries.extend(found)
        except Exception as exc:
            print(f"Archive error for {path}: {exc}")
            # A single unavailable archive should not prevent other sections
            # from producing a useful feed.
        time.sleep(1)

    unique = {}
    for entry in entries:
        unique[entry["url"]] = entry
    entries = list(unique.values())
    if not entries:
        raise RuntimeError("No entries found in Daiki Kogyo archives")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "ダイキ工業 製品情報"
    ET.SubElement(channel, "link").text = BASE
    ET.SubElement(channel, "description").text = "ダイキ工業公式サイトの製品情報のみを掲載するRSSフィード。"
    ET.SubElement(channel, "language").text = "ja"
    atom = ET.SubElement(channel, f"{{{NS['atom']}}}link")
    atom.set("href", PUBLIC_URL)
    atom.set("rel", "self")
    atom.set("type", "application/rss+xml")
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    built_items = []
    success = errors = 0
    for index, entry in enumerate(entries, 1):
        try:
            title, detail_date, description, images, body_html = extract_detail(entry["url"])
            title = title or entry["title"]
            published = detail_date or entry["date"] or datetime(2000, 1, 1, tzinfo=timezone.utc)
            built_items.append((published, entry, title, description, images, body_html))
            success += 1
            print(f"[{index}/{len(entries)}] OK category={entry['category']} images={len(images)} {entry['url']}")
        except Exception as exc:
            errors += 1
            print(f"[{index}/{len(entries)}] ERROR {entry['url']}: {exc}")
        time.sleep(1)

    built_items.sort(key=lambda row: row[0], reverse=True)
    for published, entry, title, description, images, body_html in built_items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = entry["url"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = entry["url"]
        ET.SubElement(item, "pubDate").text = format_datetime(published)
        ET.SubElement(item, "category").text = entry["category"]
        ET.SubElement(item, "description").text = description or title

        if images:
            thumb = ET.SubElement(item, f"{{{NS['media']}}}thumbnail")
            thumb.set("url", images[0])
            for image_url in images:
                media = ET.SubElement(item, f"{{{NS['media']}}}content")
                media.set("url", image_url)
                media.set("medium", "image")
            enclosure = ET.SubElement(item, "enclosure")
            enclosure.set("url", images[0])
            enclosure.set("type", "image/jpeg")
            enclosure.set("length", "0")

        if body_html:
            ET.SubElement(item, f"{{{NS['content']}}}encoded").text = body_html

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Done: {success} succeeded, {errors} failed; output={OUTPUT}")
    if success == 0:
        raise RuntimeError("No detail pages could be processed")

if __name__ == "__main__":
    main()
