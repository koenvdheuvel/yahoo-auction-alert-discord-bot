"""Marketplace adapters and shared, instrumented HTTP transport.

Adapters contain marketplace parsing only. Their immutable listings have no
Discord or persistence dependencies, and search results are streamed by page.
"""
import asyncio
from html.parser import HTMLParser
import json
import logging
import math
import re
import time
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

import aiohttp
from yarl import URL

from domain import Listing


logger = logging.getLogger(__name__)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)


class ProviderError(Exception):
    """Safe operational error: URLs, response bodies and queries are excluded."""

    def __init__(self, source, operation, reason, status=None):
        self.source, self.operation, self.reason, self.status = source, operation, reason, status
        message = f"{source} {operation}: {reason}"
        if status is not None:
            message += f" (HTTP {status})"
        super().__init__(message)


class HttpClient:
    """One session with bounded connections, timeouts and transient retries."""

    def __init__(self, settings, metrics):
        self.settings, self.metrics = settings, metrics
        self.session = None
        self._turns = {}
        self._next_request = {}

    async def start(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout),
                connector=aiohttp.TCPConnector(limit=max(1, self.settings.concurrency * 2)),
                headers={"User-Agent": USER_AGENT},
            )

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def get_json(self, source, operation, url, params=None):
        return await self._request(source, operation, url, params, self._json)

    async def get_text(self, source, operation, url, params=None, *, accept=(), interval=0):
        """An HTML page. `accept` lists error statuses whose page is still the answer.
        `interval` is the fewest seconds between two requests to this source, retries included."""
        return await self._request(source, operation, url, params, self._text, accept, interval)

    @staticmethod
    async def _json(response):
        return await response.json()

    @staticmethod
    async def _text(response):
        return await response.text()

    async def _wait_turn(self, source, interval):
        # The lock is held while sleeping, so concurrent checks of one source queue up.
        async with self._turns.setdefault(source, asyncio.Lock()):
            delay = self._next_request.get(source, 0) - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request[source] = time.monotonic() + interval

    async def _request(self, source, operation, url, params, read, accept=(), interval=0):
        if self.session is None or self.session.closed:
            raise ProviderError(source, operation, "client_not_started")
        for attempt in range(self.settings.request_retries + 1):
            if interval > 0:
                await self._wait_turn(source, interval)
            started = time.monotonic()
            outcome, status, retry_delay = "failure", None, min(0.25 * 2 ** attempt, 8)
            try:
                async with self.session.get(url, params=params) as response:
                    status = response.status
                    if (status < 200 or status >= 300) and status not in accept:
                        transient = status in {408, 425, 429, 500, 502, 503, 504}
                        reason = "transient_status" if transient else "http_status"
                        error = ProviderError(source, operation, reason, status)
                        if not transient:
                            outcome = "http_error"
                            raise error
                        header = response.headers.get("Retry-After", "")
                        try:
                            delay = float(header)
                            if math.isfinite(delay):
                                retry_delay = min(max(delay, 0), 30)
                        except ValueError:
                            pass
                        outcome = "transient_error"
                    else:
                        try:
                            body = await read(response)
                        except (json.JSONDecodeError, UnicodeDecodeError, aiohttp.ContentTypeError):
                            outcome = "invalid_response"
                            raise ProviderError(source, operation, "invalid_response") from None
                        outcome = "success"
                        return body
            except ProviderError:
                raise
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError):
                # Client exception messages commonly contain the request URL.
                outcome = "network_error"
                error = ProviderError(source, operation, "network_error", status)
            finally:
                self.metrics.requests.labels(source, operation, outcome).inc()
                self.metrics.request_duration.labels(source, operation).observe(time.monotonic() - started)
            if attempt >= self.settings.request_retries:
                raise error from None
            logger.warning("provider_request_retry", extra={"fields": {
                "source": source, "operation": operation, "attempt": attempt + 1,
                "outcome": outcome, "status": status,
            }})
            await asyncio.sleep(retry_delay)


def integer(value, source, field, *, default=None):
    """Accept integer strings while rejecting booleans and lossy conversions."""
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ProviderError(source, "parse", f"invalid_{field}")
    try:
        number = int(value)
    except ValueError:
        raise ProviderError(source, "parse", f"invalid_{field}") from None
    if number < 0:
        raise ProviderError(source, "parse", f"invalid_{field}")
    return number


class FromJapanAdapter:
    source = ""
    items_per_page = 99
    item_url = ""
    # Yahoo, Surugaya and Rakuma report an exact total; Mercari's is an estimate (see MercariAdapter).
    exact_count = True

    def __init__(self, http, settings):
        self.http, self.settings = http, settings

    @property
    def search_url(self):
        return f"https://www.fromjapan.co.jp/japan/sites/{self.source}/search"

    def _page(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ProviderError(self.source, "search", "invalid_items")
        items = payload["items"]
        count = integer(payload.get("count"), self.source, "count")
        if len(items) > self.items_per_page or (self.exact_count and len(items) > count):
            raise ProviderError(self.source, "search", "inconsistent_count")
        if any(not isinstance(item, dict) for item in items):
            raise ProviderError(self.source, "search", "invalid_item")
        return items, count

    def _pages(self, count):
        pages = max(1, (count + self.items_per_page - 1) // self.items_per_page)
        if pages > self.settings.max_pages:
            raise ProviderError(self.source, "search", "max_pages_exceeded")
        return pages

    async def _search_page(self, search_query, page):
        return await self.http.get_json(self.source, "search", self.search_url, params={
            "keyword": search_query, "sort": "score", "hits": self.items_per_page, "page": page,
        })

    async def iter_items(self, search_query):
        expected, received, pages, page = 0, 0, 1, 1
        while page <= pages:
            payload = await self._search_page(search_query, page)
            items, count = self._page(payload)
            if not items:
                # The only reliable end for estimated totals; exact ones must already be met.
                if self.exact_count and received < expected:
                    raise ProviderError(self.source, "search", "incomplete_pagination")
                return
            # Listings end or appear while a long scan runs, so every page refreshes the
            # total (e.g. Yahoo 2880 -> 2879 at page 27); completeness uses the latest one.
            expected = count
            pages = max(page, self._pages(count))
            for item in items:
                received += 1
                yield item
            page += 1
        if self.exact_count and received < expected:
            raise ProviderError(self.source, "search", "incomplete_pagination")

    def normalize(self, data):
        if not isinstance(data, dict):
            raise ProviderError(self.source, "parse", "invalid_item")
        identifier = data.get("id")
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).strip():
            raise ProviderError(self.source, "parse", "invalid_id")
        identifier = str(identifier)
        title = data.get("title") or "Unknown Title"
        image_url = data.get("imageUrl") or ""
        if not isinstance(title, str) or not isinstance(image_url, str):
            raise ProviderError(self.source, "parse", "invalid_text")
        return Listing(
            id=identifier, source=self.source, title=title,
            stock=integer(data.get("stock"), self.source, "stock", default=1 if self.source == "yahooauction" else None),
            price=integer(data.get("price"), self.source, "price"),
            buyout_price=integer(data.get("buyItNowPrice"), self.source, "buyout_price", default=0),
            image_url=self.listing_image(image_url), url=self.listing_url(data, identifier),
        )

    def listing_url(self, data, identifier):
        return self.item_url.format(id=quote(identifier, safe=""))

    def listing_image(self, image_url):
        return image_url


class YahooAuctionsAdapter(FromJapanAdapter):
    source = "yahooauction"
    item_url = "https://auctions.yahoo.co.jp/jp/auction/{id}"


class MercariAdapter(FromJapanAdapter):
    source = "mercari"
    item_url = "https://jp.mercari.com/item/{id}"
    # FromJapan's Mercari `count` changes from page to page (e.g. 127 -> 300 -> 0, or
    # 3844 -> 9319) and pages hold fewer than `hits` items.
    exact_count = False


SURUGAYA_SITE = "https://www.suruga-ya.jp"
SURUGAYA_PRODUCT = re.compile(r"/product/(?:detail|other)/([0-9A-Za-z]+)")
SURUGAYA_TOTAL = re.compile(r"該当件数[:：]\s*([\d,]+)\s*件")
# The shop's own price, as "中古：￥3,850" or a range "中古：￥3,850 ～ ￥4,100" (first is lowest).
SURUGAYA_SHOP_PRICE = re.compile(r"(?:新品|中古)[:：]\s*￥\s*([\d,]+)")
# Other sellers on suruga-ya.jp (the marketplace), shown as "マケプレ ￥2,080".
SURUGAYA_MARKET_PRICE = re.compile(r"マケプレ\s*￥\s*([\d,]+)")


class SurugayaSearchPage(HTMLParser):
    """Reads a suruga-ya.jp search page: all of its text, and the parts of each product card.

    A product card is a `<div class="item">` with an `h3.product-name` title; the page has other
    `div.item` blocks too. From a card the bot reads the first product link, the first image, the
    title and the text of `div.item_price`.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.cards = [], []
        self._card = None
        self._divs = 0
        self._title = False
        self._price_divs = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if self._card is None:
            if tag == "div" and "item" in classes:
                self._card = {"named": False, "link": None, "image": None, "title": [], "price": []}
                self._divs = 1
            return
        if tag == "div":
            self._divs += 1
            if "item_price" in classes and self._price_divs is None:
                self._price_divs = self._divs
        elif tag == "a" and self._card["link"] is None and SURUGAYA_PRODUCT.match(
                urlsplit(attrs.get("href") or "").path):
            self._card["link"] = attrs["href"]
        elif tag == "img" and self._card["image"] is None:
            self._card["image"] = attrs.get("src")
        elif tag == "h3" and "product-name" in classes:
            self._card["named"] = self._title = True

    def handle_endtag(self, tag):
        if self._card is None:
            return
        if tag == "h3":
            self._title = False
        elif tag == "div":
            if self._divs == self._price_divs:
                self._price_divs = None
            self._divs -= 1
            if self._divs == 0:
                if self._card["named"]:
                    self.cards.append(self._card)
                self._card, self._title, self._price_divs = None, False, None

    def handle_data(self, data):
        self.text.append(data)
        if self._card is not None:
            if self._title:
                self._card["title"].append(data)
            if self._price_divs is not None:
                self._card["price"].append(data)


def surugaya_item(card):
    """One card in the item shape FromJapan used, so IDs and URLs match listings saved before.

    The ID is the product link after /product/detail/ or /product/other/, with its query, such as
    `220305177?branch_number=0003`. The price is the shop's lowest price. When the shop has none
    left, it is the cheapest marketplace offer, and the link goes to /product/other/, the page
    that lists those offers. A card with neither has no price and fails as an invalid listing.
    """
    item = {"title": " ".join("".join(card["title"]).split()), "imageUrl": card["image"] or ""}
    link = urlsplit(urljoin(SURUGAYA_SITE, card["link"] or ""))
    match = SURUGAYA_PRODUCT.fullmatch(link.path)
    if link.netloc != "www.suruga-ya.jp" or not match:
        return item
    identifier = match[1] + (f"?{link.query}" if link.query else "")
    price_text = " ".join("".join(card["price"]).split())
    shop = [int(price.replace(",", "")) for price in SURUGAYA_SHOP_PRICE.findall(price_text)]
    market = SURUGAYA_MARKET_PRICE.search(price_text)
    item["id"] = identifier
    if shop:
        item.update(price=min(shop), stock=1, url=f"{SURUGAYA_SITE}{link.path}" + (
            f"?{link.query}" if link.query else ""))
    elif market:
        item.update(price=int(market[1].replace(",", "")), stock=1,
                    url=f"{SURUGAYA_SITE}/product/other/{identifier}")
    else:
        item.update(price=None, stock=0)
    return item


def parse_surugaya_search(html, source="surugaya"):
    page = SurugayaSearchPage()
    page.feed(html)
    page.close()
    total = SURUGAYA_TOTAL.search("".join(page.text))
    if not total:
        # Not a search result page: a changed layout or a block page.
        raise ProviderError(source, "search", "unexpected_page")
    return {"items": [surugaya_item(card) for card in page.cards],
            "count": int(total[1].replace(",", ""))}


class SurugayaAdapter(FromJapanAdapter):
    """Searches suruga-ya.jp itself. FromJapan's Surugaya search failed most requests with
    502 "Temporarily Unavailable" in November 2026, while suruga-ya.jp's search page answered.
    Paging and listing rules are FromJapan's, because the search page has the same order,
    page size and total, and FromJapan's IDs came from the same product links."""
    source = "surugaya"
    items_per_page = 24
    item_url = "https://www.suruga-ya.jp/product/detail/{id}"
    search_url = f"{SURUGAYA_SITE}/search"

    async def _search_page(self, search_query, page):
        query = {"category": "", "search_word": search_query}
        if page > 1:
            # The site redirects page=1 to the same URL without it.
            query["page"] = page
        # Spaces as %20: the site redirects the "+" form, which would cost a second request.
        url = URL(f"{self.search_url}?{urlencode(query, quote_via=quote)}", encoded=True)
        # A search without results is a 404 page that still shows "該当件数：0件".
        html = await self.http.get_text(self.source, "search", url, accept={404},
                                        interval=self.settings.surugaya_request_interval)
        return parse_surugaya_search(html, self.source)

    def listing_url(self, data, identifier):
        url = data.get("url")
        if isinstance(url, str) and url.startswith("https://www.suruga-ya.jp/product/"):
            return url
        return super().listing_url(data, identifier)

    def listing_image(self, image_url):
        # The card image is photo.php on www.suruga-ya.jp, which sits behind Cloudflare, so
        # Discord's image proxy can be challenged. photo.php only redirects to cdn.suruga-ya.jp
        # (plain nginx); link the CDN's JPEG directly.
        parts = urlsplit(image_url)
        if parts.scheme == "https" and parts.netloc == "www.suruga-ya.jp" and parts.path == "/database/photo.php":
            shinaban = parse_qs(parts.query).get("shinaban", [""])[0]
            if re.fullmatch(r"[0-9A-Za-z]+", shinaban):
                return f"https://cdn.suruga-ya.jp/pics/boxart_m/{shinaban.lower()}m.jpg"
        return image_url


class RakumaAdapter(FromJapanAdapter):
    # Rakuma IDs are 32 hex characters; every listing reports its stock.
    source = "rakuma"
    item_url = "https://item.fril.jp/{id}"


PROVIDERS = {provider.source: provider for provider in (
    YahooAuctionsAdapter, MercariAdapter, SurugayaAdapter, RakumaAdapter,
)}
