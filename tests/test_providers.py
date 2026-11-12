import asyncio
from builtins import anext
from dataclasses import replace
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestServer
from prometheus_client import generate_latest

from config import Settings
from observability import Metrics
from providers import (HttpClient, MercariAdapter, ProviderError, RakumaAdapter, SurugayaAdapter,
                       YahooAuctionsAdapter, parse_surugaya_search)


def surugaya_card(link, title, price_html, image="https://www.suruga-ya.jp/database/photo.php?shinaban=1&size=m"):
    """A product card as suruga-ya.jp's search page renders it (November 2026)."""
    return f"""
    <div class="item">
      <p class="condition"><span class="new_arrival red">新入荷</span></p>
      <div class="photo_box"><p class="thum"><a href="{link}"><img src="{image}" loading="lazy"></a></p></div>
      <div class="item_detail">
        <div class="title"><a href="{link}"><h3 class="product-name">{title}</h3></a></div>
        <p class="brand">[アミューズ] </p>
      </div>
      <div class="item_price padT12">
        {price_html}
        <div class="panel_buy"><p>1,500円以上は送料無料</p></div>
        <p>定価：￥9,900</p>
      </div>
    </div>"""


def surugaya_page(total, *cards):
    return f"""<html><body>
    <div class="item"><p>関連キーワード</p></div>
    <div class="hit">該当件数:{total}件中&nbsp;1-24件</div>
    {"".join(cards)}
    </body></html>"""


class HttpClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls, self.stamps = [], []
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
        self.stamps.append(time.monotonic())
        return self.responses.pop(0)

    async def fetch(self, query="test"):
        return await self.client.get_json("yahooauction", "search", self.server.make_url("/search"), {"keyword": query})

    async def test_text_pages_accept_listed_error_statuses_and_keep_requests_apart(self):
        # Surugaya's page for a search without results comes with a 404.
        self.responses = [web.Response(status=404, text="該当件数：0件"),
                          web.Response(status=503, headers={"Retry-After": "0"}), web.Response(text="ok")]
        url = self.server.make_url("/search")
        self.assertEqual(await self.client.get_text("surugaya", "search", url, accept={404}, interval=0.2),
                         "該当件数：0件")
        # The retry after the 503 waits its turn as well.
        self.assertEqual(await self.client.get_text("surugaya", "search", url, interval=0.2), "ok")
        self.assertEqual(len(self.stamps), 3)
        gaps = [later - earlier for earlier, later in zip(self.stamps, self.stamps[1:])]
        self.assertTrue(all(gap >= 0.19 for gap in gaps), gaps)
        self.responses = [web.Response(status=404, text="gone")]
        with self.assertRaisesRegex(ProviderError, "http_status"):
            await self.client.get_text("surugaya", "search", url)

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

    async def test_exact_total_changing_mid_scan_uses_latest_total(self):
        # Observed live for Yahoo "babymetal": an auction ended mid-scan, 2880 -> 2879.
        adapter = self.adapter()
        adapter.items_per_page = 2
        adapter.http.get_json.side_effect = [
            {"items": [{"id": "a"}, {"id": "b"}], "count": 5},
            {"items": [{"id": "c"}, {"id": "d"}], "count": 4},
        ]
        self.assertEqual([item["id"] async for item in adapter.iter_items("query")], ["a", "b", "c", "d"])
        self.assertEqual(adapter.http.get_json.await_count, 2)

    async def test_mercari_follows_drifting_estimate_until_empty_page(self):
        # Shape observed live for "beatmania ポスター": 127 -> 300 -> 300 -> 0 with short pages.
        adapter = self.adapter(MercariAdapter)
        adapter.items_per_page = 3
        adapter.http.get_json.side_effect = [
            {"items": [{"id": "a"}, {"id": "b"}], "count": 4},
            {"items": [{"id": "c"}], "count": 10},
            {"items": [{"id": "d"}, {"id": "e"}], "count": 10},
            {"items": [], "count": 0},
        ]
        self.assertEqual([item["id"] async for item in adapter.iter_items("query")], ["a", "b", "c", "d", "e"])
        self.assertEqual(adapter.http.get_json.await_count, 4)

    async def test_mercari_stops_when_estimate_is_reached_without_extra_request(self):
        adapter = self.adapter(MercariAdapter)
        adapter.items_per_page = 3
        adapter.http.get_json.side_effect = [{"items": [{"id": "a"}, {"id": "b"}], "count": 3}]
        self.assertEqual([item["id"] async for item in adapter.iter_items("query")], ["a", "b"])
        self.assertEqual(adapter.http.get_json.await_count, 1)

    async def test_mercari_estimate_growing_past_page_cap_fails(self):
        adapter = self.adapter(MercariAdapter, max_pages=2)
        adapter.items_per_page = 2
        adapter.http.get_json.side_effect = [
            {"items": [{"id": "a"}, {"id": "b"}], "count": 4},
            {"items": [{"id": "c"}, {"id": "d"}], "count": 9},
        ]
        received = []
        with self.assertRaisesRegex(ProviderError, "max_pages_exceeded"):
            async for item in adapter.iter_items("query"):
                received.append(item["id"])
        self.assertEqual(received, ["a", "b"])

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
        for adapter_type in (MercariAdapter, SurugayaAdapter, RakumaAdapter):
            adapter = self.adapter(adapter_type)
            for data in ({"id": "a", "price": 1}, {"id": "a", "price": 1, "stock": None}):
                with self.subTest(source=adapter.source, data=data), self.assertRaisesRegex(ProviderError, "invalid_stock"):
                    adapter.normalize(data)
            self.assertEqual(adapter.normalize({"id": "a", "price": 1, "stock": 0}).stock, 0)
        self.assertEqual(self.adapter().normalize({"id": "a", "price": 1}).stock, 1)

    def test_surugaya_keeps_canonical_product_url(self):
        adapter = self.adapter(SurugayaAdapter)
        listing = adapter.normalize({"id": "120165069", "price": 1760, "stock": 1, "title": "Japanese title",
                                     "url": "https://www.suruga-ya.jp/product/other/120165069"})
        self.assertEqual((listing.title, listing.url),
                         ("Japanese title", "https://www.suruga-ya.jp/product/other/120165069"))
        for url in (None, "", "https://evil.example/product/1", "http://www.suruga-ya.jp/product/detail/1"):
            with self.subTest(url=url):
                listing = adapter.normalize({"id": "a1", "price": 1, "stock": 0, "url": url})
                self.assertEqual(listing.url, "https://www.suruga-ya.jp/product/detail/a1")

    def test_surugaya_search_page_gives_the_ids_prices_and_links_fromjapan_gave(self):
        # Expected values are what FromJapan returned for the same cards on 2026-11-12.
        page = parse_surugaya_search(surugaya_page(
            "1,234",
            surugaya_card("/product/detail/220305177?branch_number=0003",
                          "BABYMETAL / METAL FORTH &amp; more（箱不備）",
                          '<p class="price_teika">中古：<span class="text-red"><strong>￥3,850 ～ ￥4,100 '
                          '</strong></span>&nbsp;<span class="tax">税込</span></p>'
                          '<a href="/product/other/220305177?tab=wakeari">(その他の状態)</a>'),
            surugaya_card("/product/detail/438012276?tenpo_cd=201267", "LIVE AT INTUIT DOME",
                          '<p class="price_teika"><span class="text-red">品切れ</span></p>'
                          '<p>以下からもご購入頂けます</p><a href="/product/other/438012276">マケプレ ￥6,900</a>'
                          '(1点の中古品)'),
            surugaya_card("https://www.suruga-ya.jp/product/detail/BO5012961", "Book",
                          '<p>新品：<strong>￥2,200</strong></p><p>中古：<strong>￥1,500</strong></p>'
                          '<p>以下からもご購入頂けます</p><a>マケプレ ￥900</a>'),
            surugaya_card("/product/other/120165069", "Sold out everywhere", "<p>品切れ</p>"),
            surugaya_card("/cart", "No product link", "<p>中古：￥100</p>"),
        ))
        self.assertEqual(page["count"], 1234)
        first, market, both, sold_out, broken = page["items"]
        self.assertEqual(first, {
            "id": "220305177?branch_number=0003", "title": "BABYMETAL / METAL FORTH & more（箱不備）",
            "price": 3850, "stock": 1,
            "url": "https://www.suruga-ya.jp/product/detail/220305177?branch_number=0003",
            "imageUrl": "https://www.suruga-ya.jp/database/photo.php?shinaban=1&size=m"})
        self.assertEqual((market["id"], market["price"], market["stock"], market["url"]),
                         ("438012276?tenpo_cd=201267", 6900, 1,
                          "https://www.suruga-ya.jp/product/other/438012276?tenpo_cd=201267"))
        # The shop's lowest price wins over the marketplace, even when the marketplace is cheaper.
        self.assertEqual((both["id"], both["price"]), ("BO5012961", 1500))
        adapter = self.adapter(SurugayaAdapter)
        self.assertEqual(adapter.normalize(first).image_url, "https://cdn.suruga-ya.jp/pics/boxart_m/1m.jpg")
        # Without a price or a product link a card fails as an invalid listing instead of posting.
        for item, reason in ((sold_out, "invalid_price"), (broken, "invalid_id")):
            with self.subTest(item=item), self.assertRaisesRegex(ProviderError, reason):
                adapter.normalize(item)

    def test_surugaya_pages_without_a_result_total_fail(self):
        self.assertEqual(parse_surugaya_search("<p>該当件数：0件中&nbsp;0-0件</p><p>検索結果は０件です。</p>"),
                         {"items": [], "count": 0})
        for html in ("", "<title>Just a moment...</title>", surugaya_page("x")):
            with self.subTest(html=html), self.assertRaisesRegex(ProviderError, "unexpected_page"):
                parse_surugaya_search(html)

    async def test_surugaya_scan_reads_every_page_with_one_request_each(self):
        adapter = self.adapter(SurugayaAdapter, surugaya_request_interval=7)
        adapter.items_per_page = 2
        adapter.http.get_text = AsyncMock(side_effect=[
            surugaya_page(3, *(surugaya_card(f"/product/detail/{n}", n, "<p>中古：￥100</p>") for n in "ab")),
            surugaya_page(3, surugaya_card("/product/detail/c", "c", "<p>中古：￥100</p>")),
        ])
        self.assertEqual([item["id"] async for item in adapter.iter_items("a b&c")], ["a", "b", "c"])
        first, second = adapter.http.get_text.call_args_list
        # page=1 and "+" for spaces both make the site answer with a redirect.
        self.assertEqual(str(first.args[2]), "https://www.suruga-ya.jp/search?category=&search_word=a%20b%26c")
        self.assertEqual(str(second.args[2]), "https://www.suruga-ya.jp/search?category=&search_word=a%20b%26c&page=2")
        self.assertEqual((first.kwargs["accept"], first.kwargs["interval"]), ({404}, 7))

    def test_surugaya_images_link_the_cdn_instead_of_cloudflare_photo_page(self):
        adapter = self.adapter(SurugayaAdapter)

        def image(url):
            return adapter.normalize({"id": "a1", "price": 1, "stock": 0, "imageUrl": url}).image_url

        self.assertEqual(image("https://www.suruga-ya.jp/database/photo.php?shinaban=BO5043259&size=m"),
                         "https://cdn.suruga-ya.jp/pics/boxart_m/bo5043259m.jpg")
        for url in ("", "https://www.suruga-ya.jp/database/photo.php?shinaban=../x&size=m",
                    "https://www.suruga-ya.jp/database/photo.php?size=m", "https://example.com/photo.jpg"):
            with self.subTest(url=url):
                self.assertEqual(image(url), url)


if __name__ == "__main__":
    unittest.main()
