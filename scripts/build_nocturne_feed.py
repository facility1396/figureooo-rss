#!/usr/bin/env python3
"""Create a product-only, image-rich RSS feed from nocturne.ltd."""

import os
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = "https://nocturne.ltd"
ARCHIVE = BASE + "/products/"
PUBLIC_URL = os.getenv(
    "PUBLIC_FEED_URL",
    "https://facility1396.github.io/figureooo-rss/nocturne/feed.xml",
)
OUTPUT = os.getenv("OUTPUT", "public/nocturne/feed.xml")
MAX_PAGES = int(os.getenv("MAX_PAGES", "5"))
UA = "Mozilla/5.0 (compatible; NocturneProductRSS/1.0)"

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

def fetch(url):
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 ** attempt)
    raise last_error

def text_of(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""

def is_age_gate(soup):
    """Detect a page that is only an age gate; do not attempt to bypass it."""
    title = text_of(soup.title)
    visible = text_of(soup.body)
    gate_terms = ("年齢確認", "18歳以上", "18才以上", "年齢認証")
    has_gate = any(term in title or term in visible[:1200] for term in gate_terms)
    has_product_links = bool(soup.select('h1 a[href*="/products/"], h2 a[href*="/products/"], h3 a[href*="/products/"]'))
    return has_gate and not has_product_links

def parse_release_month(value):
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月(?:発売)?", value or "")
    if match:
        year, month = map(int, match.groups())
        return datetime(year, month, 1, 12, 0, tzinfo=timezone.utc)
    return None

def parse_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return parse_release_month(value)

def image_src(img, page_url):
    value = (
        img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        or img.get("data-original") or img.get("data-original-src")
    )
    if not value:
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        choices = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
        value = choices[-1] if choices else ""
    if not value:
        return ""
    value = urljoin(page_url, value.strip())
    if value.startswith("data:") or urlparse(value).scheme not in ("http", "https"):
        return ""
    return value

def archive_items(url):
    response = fetch(url)
    soup = BeautifulSoup(response.text, "html.parser")
    if is_age_gate(soup):
        raise RuntimeError(
            "The product archive returned an age-confirmation-only page. "
            "The workflow will not bypass the site's age gate."
        )

    items = []
    seen = set()

    # The product archive links each product from a heading. This avoids
    # collecting category, brand, news, and navigation links.
    for heading in soup.select("h1, h2, h3, h4"):
        anchor = heading.find("a", href=True)
        if not anchor:
            continue
        href = urljoin(url, anchor["href"])
        parsed = urlparse(href)
        path = parsed.path.rstrip("/") + "/"
        if parsed.netloc and parsed.netloc != urlparse(BASE).netloc:
            continue
        if not path.startswith("/products/"):
            continue
        if path == "/products/" or "/page/" in path or "/tag/" in path or "/category/" in path:
            continue
        title = text_of(anchor) or text_of(heading)
        if not title or href in seen:
            continue

        # The product card usually contains its release month and a thumbnail.
        card = heading.find_parent(["article", "li"])
        if card is None:
            card = heading.parent
        card_text = text_of(card)
        release = parse_release_month(card_text)
        image = ""
        if card:
            img = card.find("img")
            if img:
                image = image_src(img, url)

        items.append({
            "url": href,
            "title": title,
            "release": release,
            "image": image,
        })
        seen.add(href)

    return items, soup

def extract_product(url, listing_item):
    response = fetch(url)
    soup = BeautifulSoup(response.text, "html.parser")
    if is_age_gate(soup):
        raise RuntimeError(
            "Product detail returned an age-confirmation-only page; no bypass attempted."
        )

    title_node = soup.select_one("h1")
    title = text_of(title_node) or listing_item["title"]

    # Find the product-specific content, not site navigation or news modules.
    body = None
    for selector in (
        ".product-content", ".entry-content", ".post-content",
        ".product-detail", "article", "main"
    ):
        candidate = soup.select_one(selector)
        if candidate and (candidate.find("img") or len(text_of(candidate)) > 100):
            body = candidate
            break

    if body:
        for unwanted in body.select("script, style, noscript, iframe, nav, footer, form"):
            unwanted.decompose()

    og_image = ""
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            og_image = urljoin(url, meta["content"].strip())
            break

    images = []
    if body:
        for img in body.find_all("img"):
            src = image_src(img, url)
            if not src:
                continue
            img["src"] = src
            for attr in (
                "data-src", "data-lazy-src", "data-original",
                "data-original-src", "srcset", "data-srcset", "loading"
            ):
                img.attrs.pop(attr, None)
            if src not in images:
                images.append(src)

    # Prefer the listing card image when OG image is absent.
    main_image = og_image or listing_item["image"]
    if main_image:
        images = [main_image] + [src for src in images if src != main_image]

    if body:
        body_html = str(body)
    else:
        body_html = ""

    if main_image and (not body or not body.find("img")):
        body_html = f'<p><img src="{main_image}" alt=""></p>' + body_html

    # Structured metadata is often exposed as Product JSON-LD.
    json_ld_text = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if raw and ("Product" in raw or "product" in raw):
            json_ld_text += raw + "\n"

    # Add visible product specification tables/dl even if outside article body.
    specs = soup.select_one(".product-spec, .specification, table, dl")
    if specs and body and not body.select_one(".product-spec, .specification, table, dl"):
        body_html += str(specs)

    release = listing_item["release"]
    if not release:
        for node in soup.select("time[datetime], meta[itemprop='releaseDate'], meta[property='product:release_date']"):
            value = node.get("datetime") or node.get("content")
            release = parse_date(value)
            if release:
                break
    if not release:
        release = datetime.now(timezone.utc)

    description = text_of(body)
    return title, release, description, images, body_html

def main():
    all_items = []
    seen = set()
    next_url = ARCHIVE

    for page_number in range(1, MAX_PAGES + 1):
        items, soup = archive_items(next_url)
        print(f"Archive page {page_number}: {len(items)} product links")
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                all_items.append(item)

        next_link = soup.select_one('a[rel="next"], .pagination a.next, a.next.page-numbers')
        if not next_link or not next_link.get("href"):
            break
        next_url = urljoin(next_url, next_link["href"])
        time.sleep(1)

    if not all_items:
        raise RuntimeError("No product entries found; refusing to publish an empty feed.")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "ノクターン 新製品情報"
    ET.SubElement(channel, "link").text = ARCHIVE
    ET.SubElement(channel, "description").text = "ノクターン公式サイトの商品一覧から取得した製品情報のみ。お知らせ・ニュースは含みません。"
    ET.SubElement(channel, "language").text = "ja"
    atom = ET.SubElement(channel, f"{{{NS['atom']}}}link")
    atom.set("href", PUBLIC_URL)
    atom.set("rel", "self")
    atom.set("type", "application/rss+xml")
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    built = []
    errors = 0
    for index, listing_item in enumerate(all_items, 1):
        try:
            title, published, description, images, body_html = extract_product(
                listing_item["url"], listing_item
            )
            built.append((published, listing_item, title, description, images, body_html))
            print(f"[{index}/{len(all_items)}] OK images={len(images)} {listing_item['url']}")
        except Exception as exc:
            errors += 1
            print(f"[{index}/{len(all_items)}] ERROR {listing_item['url']}: {exc}")
        time.sleep(1)

    if not built:
        raise RuntimeError("No product detail pages could be processed; refusing to publish an empty feed.")

    built.sort(key=lambda row: row[0], reverse=True)
    for published, listing_item, title, description, images, body_html in built:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = listing_item["url"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = listing_item["url"]
        ET.SubElement(item, "pubDate").text = format_datetime(published)
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
            ET.SubElement(item, f"{{{NS['content']}}}encoded").text = body_html

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(f"Completed: {len(built)} products, {errors} detail-page errors; output={OUTPUT}")

if __name__ == "__main__":
    main()
