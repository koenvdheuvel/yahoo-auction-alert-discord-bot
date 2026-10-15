"""Provider facts, filter policy and SQLite outbox integration without networking."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from config import Settings
from domain import Listing
from filtering import default_ruleset
from models import Filter, Item, configure_database, create_tables, database
from observability import Metrics
from providers import ProviderError, SurugayaAdapter, YahooAuctionsAdapter
from repositories import Repository
from storechecker import Ingestion, IngestionError


class FixtureProvider:
    def __init__(self, rows, adapter_type=YahooAuctionsAdapter, failure=None):
        adapter = adapter_type(SimpleNamespace(), Settings())
        self.source = adapter.source
        self.normalize = adapter.normalize
        self.rows, self.failure = rows, failure
        self.enrich = AsyncMock(side_effect=lambda item: item)

    async def iter_items(self, query):
        for row in self.rows:
            yield row
        if self.failure is not None:
            raise self.failure


def raw(identifier, title="Japanese figure", price=5000):
    return {"id": identifier, "title": title, "stock": 1, "price": price}


class IngestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        configure_database(str(Path(self.directory.name) / "alerts.db"))
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(1111, "figure")
        self.alert = (await self.repository.list_alerts())[0]
        self.ingestion = Ingestion(self.repository, self.metrics, Settings())

    async def asyncTearDown(self):
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    def item_counter(self, source, outcome):
        return self.metrics.registry.get_sample_value("auction_bot_items_total", {"source": source, "outcome": outcome})

    async def test_invalid_listing_does_not_skip_valid_siblings_and_check_is_partial(self):
        provider = FixtureProvider([raw("good-a"), raw("bad", price=None), raw("good-b")])
        with self.assertRaisesRegex(IngestionError, "1 invalid"):
            await self.ingestion.check(provider, self.alert)
        jobs = await self.repository.due_deliveries()
        self.assertEqual([json.loads(job["payload"])["listing"]["id"] for job in jobs], ["good-a", "good-b"])
        self.assertEqual(self.item_counter("yahooauction", "new"), 2)
        self.assertEqual(self.item_counter("yahooauction", "invalid"), 1)
        self.assertEqual(provider.enrich.await_count, 2)

    async def test_error_history_uses_the_published_normalization_options(self):
        ruleset = default_ruleset()
        ruleset["normalization"].update(casefold=False, kana_fold=True)
        version = await self.repository.publish_review_rules(self.alert["id"], ruleset)
        title = "ﾐｸ ＰＯＳＴＥＲ"
        provider = FixtureProvider([raw("invalid", title, price=None), raw("good", title)])
        with self.assertRaises(IngestionError):
            await self.ingestion.check(provider, self.alert)
        candidates = (await self.repository.list_candidates())["items"]
        self.assertEqual({row["normalized_title"] for row in candidates}, {"みく POSTER"})
        self.assertEqual({row["ruleset_version_id"] for row in candidates}, {version["id"]})
        self.assertEqual({row["title"] for row in candidates}, {title})
        self.assertEqual(len(await self.repository.due_deliveries()), 1)

    async def test_filter_matches_include_vetoed_titles_and_whitelists_use_any_match(self):
        whitelist_text = await self.repository.add_filter(1111, "figure", "text", "whitelist", "figure")
        whitelist_regex = await self.repository.add_filter(1111, "figure", "regex", "whitelist", "^Japanese")
        blacklist = await self.repository.add_filter(1111, "figure", "text", "blacklist", "broken")
        provider = FixtureProvider([raw("both"), raw("regex-only", "Japanese poster"),
                                    raw("blocked", "Japanese broken figure"), raw("none", "Poster")])
        await self.ingestion.check(provider, self.alert)
        jobs = await self.repository.due_deliveries()
        self.assertEqual([json.loads(job["payload"])["listing"]["id"] for job in jobs], ["both", "regex-only"])
        counts = {row["id"]: row["matches"] for row in await self.repository.list_filters(1111)}
        self.assertEqual(counts, {whitelist_text: 2, whitelist_regex: 3, blacklist: 1})
        self.assertEqual(self.item_counter("yahooauction", "filtered"), 2)

    async def test_matches_persist_when_a_later_provider_page_fails(self):
        rule = await self.repository.add_filter(1111, "figure", "text", "whitelist", "figure")
        provider = FixtureProvider([raw("good")], failure=ProviderError("yahooauction", "search", "incomplete_pagination"))
        with self.assertRaisesRegex(ProviderError, "incomplete_pagination"):
            await self.ingestion.check(provider, self.alert)
        self.assertEqual((await self.repository.list_filters(1111))[0]["id"], rule)
        self.assertEqual((await self.repository.list_filters(1111))[0]["matches"], 1)
        self.assertEqual(len(await self.repository.due_deliveries()), 1)

    async def test_disabled_legacy_filter_is_excluded_from_policy(self):
        await self.repository._call("test_legacy_filter", lambda: Filter.create(
            alert=self.alert["id"], method="legacy", type="whitelist", value="unknown", enabled=False))
        await self.ingestion.check(FixtureProvider([raw("good")]), self.alert)
        self.assertEqual(len(await self.repository.due_deliveries()), 1)
        self.assertEqual((await self.repository.list_filters(1111))[0]["matches"], 0)

    async def test_known_surugaya_title_is_reused_before_filtering_without_html_fetch(self):
        original = Listing("known", "surugaya", "Authoritative Japanese figure", 1, 5000)
        await self.repository.observe(self.alert, original)
        await self.repository.register_alert(2222, "figure")
        second = next(row for row in await self.repository.list_alerts() if row["channel_id"] == 2222)
        await self.repository.add_filter(2222, "figure", "text", "whitelist", "Authoritative")
        provider = FixtureProvider([raw("known", "Translated title")], SurugayaAdapter)
        provider.enrich.side_effect = AssertionError("existing title must avoid enrichment")
        await self.ingestion.check(provider, second)
        provider.enrich.assert_not_awaited()
        jobs = await self.repository.due_deliveries()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(json.loads(jobs[1]["payload"])["listing"]["title"], original.title)

    async def test_blacklist_skips_enrichment_and_preserves_observation(self):
        original = Listing("known", "surugaya", "Authoritative Japanese figure", 1, 5000)
        await self.repository.observe(self.alert, original)
        item = await self.repository._call("test_item", lambda: Item.get(Item.item_id == "known").id)
        await self.repository.blacklist_item(item, 1111)
        provider = FixtureProvider([raw("known", "Translated title", price=3000)], SurugayaAdapter)
        provider.enrich.side_effect = AssertionError("blacklist must avoid enrichment")
        await self.ingestion.check(provider, self.alert)
        provider.enrich.assert_not_awaited()
        self.assertEqual(self.item_counter("surugaya", "blacklisted"), 1)
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual(await self.repository._call("test_price", lambda: Item.get_by_id(item).price), 5000)

    async def test_enrichment_failure_processes_valid_sibling_and_marks_partial(self):
        provider = FixtureProvider([raw("failed"), raw("good")], SurugayaAdapter)
        provider.enrich.side_effect = [ProviderError("surugaya", "title", "missing_title"),
                                       Listing("good", "surugaya", "Authoritative good", 1, 5000)]
        with self.assertRaisesRegex(IngestionError, "1 invalid"):
            await self.ingestion.check(provider, self.alert)
        jobs = await self.repository.due_deliveries()
        self.assertEqual([json.loads(job["payload"])["listing"]["id"] for job in jobs], ["good"])
        self.assertEqual(self.item_counter("surugaya", "enrichment_error"), 1)


if __name__ == "__main__":
    unittest.main()
