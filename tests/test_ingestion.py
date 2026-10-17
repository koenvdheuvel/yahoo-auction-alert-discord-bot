"""Provider facts, filter policy and SQLite outbox integration without networking."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from config import Settings
from domain import Listing
from filtering import default_ruleset
from models import Filter, Item, configure_database, create_tables, database
from observability import Metrics
from providers import ProviderError, RakumaAdapter, SurugayaAdapter, YahooAuctionsAdapter
from repositories import Repository
from storechecker import Ingestion, IngestionError


class FixtureProvider:
    def __init__(self, rows, adapter_type=YahooAuctionsAdapter, failure=None):
        adapter = adapter_type(SimpleNamespace(), Settings())
        self.source = adapter.source
        self.normalize = adapter.normalize
        self.rows, self.failure = rows, failure

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

    async def test_blacklist_preserves_observation(self):
        original = Listing("known", "surugaya", "Authoritative Japanese figure", 1, 5000)
        await self.repository.observe(self.alert, original)
        item = await self.repository._call("test_item", lambda: Item.get(Item.item_id == "known").id)
        await self.repository.blacklist_item(item, 1111)
        provider = FixtureProvider([raw("known", "Translated title", price=3000)], SurugayaAdapter)
        await self.ingestion.check(provider, self.alert)
        self.assertEqual(self.item_counter("surugaya", "blacklisted"), 1)
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual(await self.repository._call("test_price", lambda: Item.get_by_id(item).price), 5000)

    async def turn_on_again(self, source):
        await self.repository.set_alert_source(1111, "figure", source, False)
        await self.repository.set_alert_source(1111, "figure", source, True)

    async def state(self, source):
        return (await self.repository.source_states())[self.alert["id"]][source]

    async def test_a_marketplace_turned_on_saves_what_it_has_then_posts_only_new_listings(self):
        await self.turn_on_again("rakuma")
        self.assertEqual(await self.state("rakuma"), (True, False))
        provider = FixtureProvider([raw("old-a"), raw("old-b")], RakumaAdapter,
                                   failure=ProviderError("rakuma", "search", "incomplete_pagination"))
        # A check that does not read every page leaves it unseeded: the next check still posts nothing.
        with self.assertRaises(ProviderError):
            await self.ingestion.check(provider, self.alert, seeding=True)
        self.assertEqual(await self.state("rakuma"), (True, False))
        provider.failure = None
        provider.rows.append(raw("old-c"))
        await self.ingestion.check(provider, self.alert, seeding=True)
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual(self.item_counter("rakuma", "seeded"), 3)
        self.assertEqual(await self.state("rakuma"), (True, True))
        provider.rows.append(raw("fresh"))
        await self.ingestion.check(provider, self.alert)
        jobs = await self.repository.due_deliveries()
        self.assertEqual([json.loads(job["payload"])["listing"]["id"] for job in jobs], ["fresh"])
        self.assertEqual(json.loads(jobs[0]["payload"])["listing"]["url"], "https://item.fril.jp/fresh")

    async def test_a_marketplace_turned_off_during_its_first_check_stays_off(self):
        await self.turn_on_again("rakuma")
        repository = self.repository

        class TurnedOffMidway(FixtureProvider):
            async def iter_items(self, query):
                yield raw("a")
                await repository.set_alert_source(1111, "figure", "rakuma", False)
                yield raw("b")

        await self.ingestion.check(TurnedOffMidway([], RakumaAdapter), self.alert, seeding=True)
        self.assertEqual(await self.state("rakuma"), (False, True))
        self.assertEqual(await self.repository.due_deliveries(), [])


if __name__ == "__main__":
    unittest.main()
