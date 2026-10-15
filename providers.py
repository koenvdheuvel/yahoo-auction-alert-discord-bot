"""Marketplace adapters and shared, instrumented HTTP transport.

Adapters contain marketplace parsing only. Their immutable listings have no
Discord or persistence dependencies, and search results are streamed by page.
"""
import asyncio
from collections import OrderedDict
from dataclasses import replace
import json
import logging
import math
import time
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

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
        return await self._request(source, operation, url, params, json_response=True)

    async def get_text(self, source, operation, url, params=None):
        return await self._request(source, operation, url, params, json_response=False)

    async def _request(self, source, operation, url, params, *, json_response):
        if self.session is None or self.session.closed:
            raise ProviderError(source, operation, "client_not_started")
        for attempt in range(self.settings.request_retries + 1):
            started = time.monotonic()
            outcome, status, retry_delay = "failure", None, min(0.25 * 2 ** attempt, 8)
            try:
                async with self.session.get(url, params=params) as response:
                    status = response.status
                    if status < 200 or status >= 300:
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
                            body = await response.json() if json_response else await response.text()
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
    color = 0
    items_per_page = 99
    item_url = ""

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
        if len(items) > self.items_per_page or len(items) > count:
            raise ProviderError(self.source, "search", "inconsistent_count")
        if any(not isinstance(item, dict) for item in items):
            raise ProviderError(self.source, "search", "invalid_item")
        return items, count

    async def iter_items(self, search_query):
        expected, received, pages = None, 0, 1
        page = 1
        while page <= pages:
            payload = await self.http.get_json(self.source, "search", self.search_url, params={
                "keyword": search_query, "sort": "score", "hits": self.items_per_page, "page": page,
            })
            items, count = self._page(payload)
            if expected is None:
                expected = count
                pages = max(1, (expected + self.items_per_page - 1) // self.items_per_page)
                if pages > self.settings.max_pages:
                    raise ProviderError(self.source, "search", "max_pages_exceeded")
            if not items and received < expected:
                raise ProviderError(self.source, "search", "incomplete_pagination")
            for item in items:
                received += 1
                yield item
            page += 1
        if received != expected:
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
            image_url=image_url, url=self.item_url.format(id=quote(identifier, safe="")),
        )

    async def enrich(self, listing):
        return listing


class YahooAuctionsAdapter(FromJapanAdapter):
    source = "yahooauction"
    color = 0xFFA500
    item_url = "https://buyee.jp/item/yahoo/auction/{id}"


class MercariAdapter(FromJapanAdapter):
    source = "mercari"
    color = 0xFF0000
    item_url = "https://jp.mercari.com/item/{id}"


class SurugayaAdapter(FromJapanAdapter):
    source = "surugaya"
    color = 0x0000FF
    items_per_page = 24
    item_url = "https://www.suruga-ya.jp/product/detail/{id}"
    title_cache_size = 512

    def __init__(self, http, settings):
        super().__init__(http, settings)
        self._titles = OrderedDict()
        self._inflight = {}

    async def enrich(self, listing):
        if listing.id in self._titles:
            self._titles.move_to_end(listing.id)
            return replace(listing, title=self._titles[listing.id])
        pending = self._inflight.get(listing.id)
        if pending is not None:
            return replace(listing, title=await asyncio.shield(pending))
        pending = asyncio.get_running_loop().create_future()
        self._inflight[listing.id] = pending
        try:
            html = await self.http.get_text(self.source, "title", listing.url)
            soup = BeautifulSoup(html, "html.parser")
            heading = soup.find("h1", id="item_title")
            title = heading.get_text(" ", strip=True) if heading is not None else ""
            if not title:
                raise ProviderError(self.source, "title", "missing_title")
            self._titles[listing.id] = title
            self._titles.move_to_end(listing.id)
            while len(self._titles) > self.title_cache_size:
                self._titles.popitem(last=False)
            pending.set_result(title)
            return replace(listing, title=title)
        except BaseException as exc:
            # Coalesced waiters receive an operational failure when the owning
            # check is cancelled. No detached task survives a timed-out check.
            failure = ProviderError(self.source, "title", "request_cancelled") if isinstance(exc, asyncio.CancelledError) else exc
            pending.set_exception(failure)
            pending.exception()
            raise
        finally:
            self._inflight.pop(listing.id, None)


PROVIDERS = {provider.source: provider for provider in (
    YahooAuctionsAdapter, MercariAdapter, SurugayaAdapter,
)}
