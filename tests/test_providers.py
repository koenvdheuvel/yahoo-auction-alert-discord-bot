import asyncio
from builtins import anext
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestServer
from prometheus_client import generate_latest

from config import Settings
from observability import Metrics
from providers import HttpClient, MercariAdapter, ProviderError, SurugayaAdapter, YahooAuctionsAdapter


class HttpClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.responses = []
        app = web.Application()
        app.router.add_get("/search", self.serve)
        self.server = TestServer(app)
        await self.server.start_server()
        self.metrics = Metrics()
        self.client = HttpClient(Settings(request_retries=2), self.metrics)
        await self.client.start()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def serve(self, request):
        self.calls.append(dict(request.query))
        return self.responses.pop(0)

    async def fetch(self, query="test"):
        return await self.client.get_json("yahooauction", "search", self.server.make_url("/search"), {"keyword": query})

    def counter(self, outcome):
        return self.metrics.registry.get_sample_value("auction_bot_provider_requests_total", {
            "source": "yahooauction", "operation": "search", "outcome": outcome,
        })

    async def test_reuses_session_and_encodes_query_without_metric_labels(self):
        self.responses = [web.json_response({"items": [], "count": 0}) for _ in range(2)]
        session = self.client.session
        query = "日本語 & x=1 #suffix + slash/"
        await self.fetch(query)
        await self.fetch(query)
        self.assertIs(self.client.session, session)
        self.assertEqual(self.calls, [{"keyword": query}, {"keyword": query}])
        self.assertEqual(self.counter("success"), 2)
        self.assertNotIn("keyword", generate_latest(self.metrics.registry).decode())
        self.assertNotIn(query, generate_latest(self.metrics.registry).decode())

    async def test_retries_transient_status_then_succeeds(self):
        self.responses = [web.Response(status=503, headers={"Retry-After": "0"}), web.json_response({"ok": True})]
        self.assertEqual(await self.fetch(), {"ok": True})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.counter("transient_error"), 1)
        self.assertEqual(self.counter("success"), 1)

    async def test_retry_budget_is_bounded(self):
        self.responses = [web.Response(status=429, headers={"Retry-After": "0"}) for _ in range(3)]
        with self.assertRaisesRegex(ProviderError, "transient_status") as failure:
            await self.fetch("sensitive-query")
        self.assertEqual(failure.exception.status, 429)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.counter("transient_error"), 3)
        self.assertNotIn("sensitive-query", str(failure.exception))

    async def test_permanent_status_is_not_retried(self):
        self.responses = [web.Response(status=403, text="private upstream response")]
        with self.assertRaisesRegex(ProviderError, "http_status") as failure:
            await self.fetch()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.counter("http_error"), 1)
        self.assertNotIn("private", str(failure.exception))

    async def test_invalid_json_is_not_retried(self):
        self.responses = [web.Response(text="{invalid}", content_type="application/json")]
        with self.assertRaisesRegex(ProviderError, "invalid_response"):
            await self.fetch()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.counter("invalid_response"), 1)

    async def test_network_failures_use_same_retry_budget(self):
        await self.client.close()
        self.client.session = SimpleNamespace(closed=False, get=unittest.mock.Mock(side_effect=asyncio.TimeoutError))
        with unittest.mock.patch("providers.asyncio.sleep", new=AsyncMock()):
            with self.assertRaisesRegex(ProviderError, "network_error"):
                await self.fetch()
        self.assertEqual(self.client.session.get.call_count, 3)
        self.assertEqual(self.counter("network_error"), 3)
        self.client.session = None


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, adapter_type=YahooAuctionsAdapter, **settings):
        http = SimpleNamespace(get_json=AsyncMock())
        return adapter_type(http, replace(Settings(), **settings))

    async def test_pages_are_fetched_only_as_iterator_advances(self):
        adapter = self.adapter()
        adapter.items_per_page = 2
        adapter.http.get_json.side_effect = [
            {"items": [{"id": "a"}, {"id": "b"}], "count": 3},
            {"items": [{"id": "c"}], "count": 3},
        ]
        results = adapter.iter_items("query")
        self.assertEqual(await anext(results), {"id": "a"})
        self.assertEqual(adapter.http.get_json.await_count, 1)
        self.assertEqual(await anext(results), {"id": "b"})
        self.assertEqual(adapter.http.get_json.await_count, 1)
        self.assertEqual(await anext(results), {"id": "c"})
        self.assertEqual(adapter.http.get_json.await_count, 2)
        with self.assertRaises(StopAsyncIteration):
            await anext(results)
        self.assertEqual(adapter.http.get_json.call_args_list[1].kwargs["params"]["page"], 2)

    async def test_max_pages_fails_before_yielding_partial_results(self):
        adapter = self.adapter(max_pages=1)
        adapter.http.get_json.return_value = {"items": [{"id": "a"}], "count": 100}
        with self.assertRaisesRegex(ProviderError, "max_pages_exceeded"):
            await anext(adapter.iter_items("query"))
        self.assertEqual(adapter.http.get_json.await_count, 1)

    async def test_incomplete_final_page_is_reported_as_failure(self):
        adapter = self.adapter()
        adapter.items_per_page = 2
        adapter.http.get_json.side_effect = [
            {"items": [{"id": "a"}, {"id": "b"}], "count": 4},
            {"items": [{"id": "c"}], "count": 4},
        ]
        received = []
        with self.assertRaisesRegex(ProviderError, "incomplete_pagination"):
            async for item in adapter.iter_items("query"):
                received.append(item["id"])
        self.assertEqual(received, ["a", "b", "c"])

    async def test_empty_results_are_successful(self):
        adapter = self.adapter()
        adapter.http.get_json.return_value = {"items": [], "count": 0}
        self.assertEqual([item async for item in adapter.iter_items("query")], [])

    async def test_invalid_shapes_and_counts_fail(self):
        invalid = [None, [], {}, {"items": {}, "count": 0}, {"items": [], "count": -1},
                   {"items": [], "count": True}, {"items": [], "count": 1.5},
                   {"items": [{"id": "a"}], "count": 0}, {"items": ["wrong"], "count": 1}]
        for payload in invalid:
            with self.subTest(payload=payload):
                adapter = self.adapter()
                adapter.http.get_json.return_value = payload
                with self.assertRaises(ProviderError):
                    await anext(adapter.iter_items("query"))

    def test_normalization_is_pure_and_coerces_valid_numbers(self):
        adapter = self.adapter()
        listing = adapter.normalize({"id": "item/1", "price": "1234", "buyItNowPrice": None, "title": None})
        self.assertEqual((listing.source, listing.stock, listing.price, listing.buyout_price), ("yahooauction", 1, 1234, 0))
        self.assertEqual(listing.title, "Unknown Title")
        self.assertTrue(listing.url.endswith("item%2F1"))
        adapter.http.get_json.assert_not_called()
        listing = self.adapter(MercariAdapter).normalize({"id": "m1", "stock": "2", "price": 2500})
        self.assertEqual((listing.stock, listing.price), (2, 2500))

    def test_malformed_listing_cannot_become_zero_price_alert(self):
        for data in [{"id": "a"}, {"id": "a", "price": None}, {"id": "a", "price": 1.5},
                     {"id": "a", "price": True}, {"id": "a", "price": -1}, {"price": 1}]:
            with self.subTest(data=data), self.assertRaises(ProviderError):
                self.adapter().normalize(data)

    def test_non_auction_missing_stock_is_rejected_while_explicit_zero_is_valid(self):
        for adapter_type in (MercariAdapter, SurugayaAdapter):
            adapter = self.adapter(adapter_type)
            for data in ({"id": "a", "price": 1}, {"id": "a", "price": 1, "stock": None}):
                with self.subTest(source=adapter.source, data=data), self.assertRaisesRegex(ProviderError, "invalid_stock"):
                    adapter.normalize(data)
            self.assertEqual(adapter.normalize({"id": "a", "price": 1, "stock": 0}).stock, 0)
        self.assertEqual(self.adapter().normalize({"id": "a", "price": 1}).stock, 1)

    def test_surugaya_uses_fromjapan_title_and_canonical_product_url(self):
        adapter = self.adapter(SurugayaAdapter)
        listing = adapter.normalize({"id": "120165069", "price": 1760, "stock": 1, "title": "Japanese title",
                                     "url": "https://www.suruga-ya.jp/product/other/120165069"})
        self.assertEqual((listing.title, listing.url),
                         ("Japanese title", "https://www.suruga-ya.jp/product/other/120165069"))
        for url in (None, "", "https://evil.example/product/1", "http://www.suruga-ya.jp/product/detail/1"):
            with self.subTest(url=url):
                listing = adapter.normalize({"id": "a1", "price": 1, "stock": 0, "url": url})
                self.assertEqual(listing.url, "https://www.suruga-ya.jp/product/detail/a1")


if __name__ == "__main__":
    unittest.main()
