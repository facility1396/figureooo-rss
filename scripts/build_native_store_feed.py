#!/usr/bin/env python3
"""Build an image-rich RSS feed for every brand in native STORE's product catalog.

The public product listing is polled each run. Product detail pages are fetched
only for products not already present in the previous generated feed, which
keeps recurring traffic low. No login or age-gate bypass is attempted.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin, urlparse, urlencode
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = "https://native-store.net"
LIST_URL = BASE + "/ja/products/list"
PUBLIC_URL = os.getenv(
    "PUBLIC_FEED_URL",
    "https://facility1396.github.io/figureooo-rss/native-store/feed.xml",
)
OUTPUT = os.getenv("OUTPUT", "public/native-store/feed.xml")
MAX_PAGES = int(os.getenv("MAX_PAGES", "25"))
PAGE_DELAY = float(os.getenv("PAGE_DELAY", "1.5"))
DETAIL_DELAY = float(os.getenv("DETAIL_DELAY", "1.0"))
UA = "Mozilla/5.0 (compatible; NativeStoreProductRSS/1.0)"

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
    last = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=35)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise last

def norm_space(value):
    return re.sub(r"\s+", " ", value or "").strip()

def text_of(node):
    return norm_space(node.get_text(" ", strip=True)) if node else ""

def is_gate(soup):
    title = text_of(soup.title)
    body = text_of(soup.body)[:1600]
    terms = ("年齢確認", "18歳以上", "18才以上", "年齢認証")
    return any(t in title or t in body for t in terms) and not soup.select(
        'a[href*="/products/detail/"]'
    )

def absolute_image(img, page_url):
    value = (
        img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        or img.get("data-original") or img.get("data-original-src")
    )
    if not value:
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        choices = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
        value = choices[-1] if choices else ""
    if not value:
        return ""
    value = urljoin(page_url, value.strip())
    if value.startswith("data:") or urlparse(value).scheme not in ("http", "https"):
        return ""
    return value

def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        pass
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月(?:\s*(\d{1,2})日)?", value)
    if m:
        y, month = int(m.group(1)), int(m.group(2))
        day = int(m.group(3) or 1)
        return datetime(y, month, day, 12, 0, tzinfo=timezone.utc)
    return None

def card_for(anchor):
    selectors = (
        ".ec-shelfGrid__item", ".ec-productRole", ".product-item",
        ".productItem", ".item_box", "li", "article"
    )
    for selector in selectors:
        parent = anchor.find_parent(class_=lambda c: c and selector.lstrip(".") in c.split()) if selector.startswith(".") else anchor.find_parent(selector)
        if parent:
            # Avoid accidentally returning a page-wide list container.
            if len(parent.find_all("a", href=True)) <= 12:
                return parent
    return anchor.parent

def get_brand(card):
    if not card:
        return ""
    for selector in (".maker", ".brand", ".ec-productRole__brand", ".product-brand"):
        node = card.select_one(selector)
        if node and text_of(node):
            return text_of(node)
    return ""

def parse_listing_page(page_number):
    params = {"pageno": str(page_number)}
    url = LIST_URL + "?" + urlencode(params)
    response = fetch(url)
    soup = BeautifulSoup(response.text, "html.parser")
    if is_gate(soup):
        raise RuntimeError(
            "The public listing returned an age-confirmation-only page. "
            "No age gate or login restriction will be bypassed."
        )

    found = []
    seen = set()
    anchors = soup.select('a[href*="/ja/products/detail/"], a[href*="/products/detail/"]')

    # Some EC-CUBE themes use product links without a detail URL in the path.
    if not anchors:
        for selector in (
            ".ec-shelfGrid__item a[href]",
            ".ec-productRole a[href]",
            ".product-item a[href]",
        ):
            anchors.extend(soup.select(selector))

    for anchor in anchors:
        href = urljoin(url, anchor.get("href", ""))
        parsed = urlparse(href)
        if parsed.netloc != urlparse(BASE).netloc:
            continue
        if "/products/detail/" not in parsed.path:
            continue
        if href in seen:
            continue

        card = card_for(anchor)
        title = text_of(anchor)
        if not title or title in ("詳細を見る", "詳しく見る", "More"):
            title_node = card.select_one("h2,h3,h4,.ec-shelfGrid__item-name,.product-name") if card else None
            title = text_of(title_node)
        if not title:
            title = text_of(soup.select_one("h1"))
        if not title:
            continue

        img = card.find("img") if card else None
        thumb = absolute_image(img, url) if img else ""
        card_text = text_of(card)
        price_match = re.search(r"[￥¥]\s*[\d,]+", card_text)
        price = price_match.group(0).replace(" ", "") if price_match else ""
        status = ""
        for word in ("予約受付中", "注文期間外", "SOLD OUT", "在庫あり", "販売終了"):
            if word in card_text:
                status = word
                break

        found.append({
            "url": href,
            "title": title,
            "image": thumb,
            "price": price,
            "status": status,
            "brand": get_brand(card),
        })
        seen.add(href)

    return found, soup

def load_previous_items():
    """Reuse previously expanded detail HTML to avoid re-fetching old products."""
    cache = {}
    try:
        response = session.get(PUBLIC_URL, timeout=20)
        if response.status_code != 200:
            return cache
        root = ET.fromstring(response.content)
        for item in root.findall("./channel/item"):
            link = item.findtext("link", "").strip()
            if link:
                cache[link] = item
    except Exception as exc:
        print(f"Previous feed cache unavailable; first run may be larger: {exc}")
    return cache

def detail_content(url, listing):
    response = fetch(url)
    soup = BeautifulSoup(response.text, "html.parser")
    if is_gate(soup):
        raise RuntimeError("Product detail page requires an age confirmation; no bypass attempted.")

    title = text_of(soup.select_one("h1")) or listing["title"]

    # Prefer the product description area and avoid NEWS, navigation, and footer.
    body = None
    for selector in (
        ".ec-productRole__description", ".ec-productRole",
        ".product-detail", ".product-description", ".entry-content",
        "main article", "main"
    ):
        candidate = soup.select_one(selector)
        if candidate and (candidate.find("img") or len(text_of(candidate)) > 80):
            body = candidate
            break

    if body:
        for unwanted in body.select("script,style,noscript,iframe,nav,footer,form,button"):
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
            src = absolute_image(img, url)
            if not src:
                continue
            img["src"] = src
            for attr in ("data-src", "data-lazy-src", "data-original", "srcset", "data-srcset", "loading"):
                img.attrs.pop(attr, None)
            if src not in images:
                images.append(src)

    main_image = og_image or listing["image"]
    if main_image:
        images = [main_image] + [src for src in images if src != main_image]

    # Parse Product JSON-LD for reliable price and availability where available.
    json_products = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            candidates = data if isinstance(data, list) else [data]
            for candidate in candidates:
                if isinstance(candidate, dict) and "@graph" in candidate:
                    candidates.extend(x for x in candidate["@graph"] if isinstance(x, dict))
                if isinstance(candidate, dict) and (
                    candidate.get("@type") == "Product"
                    or "Product" in (candidate.get("@type") or [])
                ):
                    json_products.append(candidate)
        except Exception:
            continue

    price = listing["price"]
    status = listing["status"]
    published = None
    for product in json_products:
        offers = product.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            amount = offers.get("price")
            if amount:
                price = f"￥{int(float(amount)):,}" if str(amount).replace(".", "", 1).isdigit() else str(amount)
            availability = str(offers.get("availability", ""))
            if "InStock" in availability:
                status = status or "販売中"
            elif "OutOfStock" in availability:
                status = status or "SOLD OUT"
        published = parse_date(product.get("releaseDate") or product.get("datePublished")) or published

    if not published:
        meta = soup.find("meta", attrs={"property": "article:published_time"})
        if meta:
            published = parse_date(meta.get("content"))
    if not published:
        published = datetime.now(timezone.utc)

    description = text_of(body)
    if not description:
        meta = soup.find("meta", attrs={"name": "description"})
        description = norm_space(meta.get("content", "")) if meta else title

    body_html = str(body) if body else ""
    if main_image and (not body or not body.find("img")):
        body_html = f'<p><img src="{main_image}" alt=""></p>' + body_html

    # Include the concise listing status/price in the RSS summary.
    summary_bits = [x for x in (listing["brand"], price, status) if x]
    summary = " / ".join(summary_bits + [description]) if summary_bits else description

    return title, published, summary, images, body_html, price, status

def main():
    previous = load_previous_items()
    products = []
    seen = set()
    empty_pages = 0

    for page_number in range(1, MAX_PAGES + 1):
        entries, soup = parse_listing_page(page_number)
        print(f"Product list page {page_number}: {len(entries)} products")
        if not entries:
            empty_pages += 1
            if empty_pages >= 1:
                break
        else:
            empty_pages = 0
            for entry in entries:
                if entry["url"] not in seen:
                    seen.add(entry["url"])
                    products.append(entry)

        # If the page has no next-page control and fewer than a full page of cards,
        # there is no reason to keep probing additional page numbers.
        next_link = soup.select_one('a[rel="next"], .ec-pager__item--next a, a.next')
        if not next_link and len(entries) < 10:
            break
        time.sleep(PAGE_DELAY)

    if not products:
        raise RuntimeError("No products found in the Native Store all-products listing.")

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "native STORE 全ブランド新製品・商品情報"
    ET.SubElement(channel, "link").text = LIST_URL
    ET.SubElement(channel, "description").text = "native STOREの商品一覧（全ブランド）から取得した商品情報。NEWS・お知らせは含みません。"
    ET.SubElement(channel, "language").text = "ja"
    atom = ET.SubElement(channel, f"{{{NS['atom']}}}link")
    atom.set("href", PUBLIC_URL)
    atom.set("rel", "self")
    atom.set("type", "application/rss+xml")
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    built = []
    errors = 0
    reused = 0
    for index, product in enumerate(products, 1):
        old = previous.get(product["url"])
        if old is not None:
            # Reuse previously fetched full item markup. Refresh listing-level
            # status/price in the summary when present.
            if product["price"] or product["status"]:
                description = old.find("description")
                detail_text = description.text or "" if description is not None else ""
                bits = [x for x in (product["brand"], product["price"], product["status"]) if x]
                if bits:
                    updated_summary = " / ".join(bits)
                    if detail_text and updated_summary not in detail_text:
                        updated_summary += " / " + detail_text
                    if description is None:
                        description = ET.SubElement(old, "description")
                    description.text = updated_summary
            built.append(old)
            reused += 1
            continue

        try:
            title, published, summary, images, body_html, price, status = detail_content(
                product["url"], product
            )
            item = ET.Element("item")
            ET.SubElement(item, "title").text = title
            ET.SubElement(item, "link").text = product["url"]
            ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = product["url"]
            ET.SubElement(item, "pubDate").text = format_datetime(published)
            ET.SubElement(item, "category").text = product["brand"] or "商品情報"
            ET.SubElement(item, "description").text = summary

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

            built.append(item)
            print(f"[{index}/{len(products)}] NEW OK images={len(images)} {product['url']}")
        except Exception as exc:
            errors += 1
            print(f"[{index}/{len(products)}] NEW ERROR {product['url']}: {exc}")
        time.sleep(DETAIL_DELAY)

    if not built:
        raise RuntimeError("No product items could be written; refusing to publish an empty feed.")

    for item in built:
        channel.append(item)

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)
    print(
        f"Done: {len(built)} products in feed; reused={reused}; "
        f"new detail errors={errors}; output={OUTPUT}"
    )

if __name__ == "__main__":
    main()
