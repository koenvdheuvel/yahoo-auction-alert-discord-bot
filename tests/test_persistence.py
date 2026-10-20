"""Real SQLite migration, identity and transactional outbox guarantees."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from peewee import IntegrityError

from domain import Listing
from models import (Alert, AlertItem, AlertSource, Blacklist, DeliveryJob, Filter, Item, Message,
                    Notification, SCHEMA_VERSION, SchemaVersion, configure_database, create_tables, database)
from observability import Metrics
from repositories import Repository


def listing(source="yahooauction", external_id="same-id", price=5000):
    return Listing(external_id, source, "Japanese figure", 1, price, url="https://example.com/item")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "legacy.db"
        with sqlite3.connect(self.path) as connection:
            connection.executescript("""
                CREATE TABLE alert (id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL,
                                    search_query TEXT NOT NULL UNIQUE);
                CREATE TABLE item (id INTEGER PRIMARY KEY, item_id TEXT NOT NULL UNIQUE,
                    checker TEXT, title TEXT, stock INTEGER DEFAULT 0, price INTEGER DEFAULT 0,
                    buyout_price INTEGER DEFAULT 0, message_id INTEGER UNIQUE, muted INTEGER DEFAULT 0,
                    found_at DATETIME, updated_at DATETIME, alert_id INTEGER REFERENCES alert(id));
                CREATE TABLE blacklist (id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id), channel_id INTEGER);
                CREATE TABLE notification (id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id), user_id TEXT);
                CREATE TABLE filter (id INTEGER PRIMARY KEY, alert_id INTEGER REFERENCES alert(id),
                                     type TEXT, value TEXT, inverse INTEGER DEFAULT 0, matches INTEGER DEFAULT 0);
                INSERT INTO alert VALUES (11, 1111, 'figure'), (12, 2222, 'music');
                INSERT INTO item VALUES (101, 'auction-id', 'YahooAuctionsChecker', 'Old title', 1, 5000,
                    7000, 50001, 1, '2025-01-01 01:02:03', '2025-01-02 04:05:06', 11);
                INSERT INTO item VALUES (102, 'mercari-id', 'MercariChecker', 'Music title', 2, 3000,
                    0, 50002, 0, '2025-01-03 01:02:03', NULL, 12);
                INSERT INTO notification VALUES (201, 101, '42'), (202, 101, '42'), (203, 102, '43'), (204, 999, '44');
                INSERT INTO blacklist VALUES (301, 101, 1111), (302, 101, 1111), (303, 999, 2222);
                INSERT INTO filter VALUES (401, 11, 'whitelist', 'lost matcher', 0, 5),
                    (402, 11, 'regex', '^figure', 0, 6), (403, 12, 'text', 'damaged', 1, 7),
                    (404, 999, 'text', 'orphan', 0, 0);
            """)
        configure_database(str(self.path))
        create_tables()
        database.connect(reuse_if_open=True)

    def tearDown(self):
        database.close()
        self.directory.cleanup()

    def test_backup_retains_original_schema_and_duplicate_rows(self):
        backups = list(self.path.parent.glob(f"legacy.db.pre-v{SCHEMA_VERSION}.*.bak"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as backup:
            columns = [row[1] for row in backup.execute("PRAGMA table_info(item)")]
            self.assertIn("message_id", columns)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM notification").fetchone()[0], 4)
            self.assertEqual(backup.execute("SELECT message_id FROM item WHERE id=101").fetchone()[0], 50001)

    def test_ids_source_names_baselines_and_latest_message_mapping_survive(self):
        self.assertEqual(SchemaVersion.get_by_id(1).version, SCHEMA_VERSION)
        auction = Item.get_by_id(101)
        self.assertEqual((auction.item_id, auction.checker, auction.price, auction.buyout_price, auction.muted),
                         ("auction-id", "yahooauction", 5000, 7000, True))
        self.assertEqual(auction.found_at.isoformat(), "2025-01-01T01:02:03")
        self.assertEqual(Item.get_by_id(102).checker, "mercari")
        self.assertEqual(set(Alert.select(Alert.id).tuples()), {(11,), (12,)})
        self.assertEqual(set(AlertItem.select(AlertItem.alert, AlertItem.item, AlertItem.price).tuples()),
                         {(11, 101, 5000), (12, 102, 3000)})
        self.assertEqual(set(Message.select(Message.message_id, Message.item, Message.alert, Message.channel_id).tuples()),
                         {(50001, 101, 11, 1111), (50002, 102, 12, 2222)})
        # The searches go on posting what is new on the marketplaces they checked; Rakuma starts quietly.
        self.assertEqual(set(AlertSource.select(AlertSource.alert, AlertSource.source, AlertSource.enabled,
                                                AlertSource.seeded).tuples()),
                         {(alert, source, True, True) for alert in (11, 12)
                          for source in ("yahooauction", "mercari", "surugaya")})

    def test_duplicates_orphans_and_lost_filter_method_are_handled_explicitly(self):
        self.assertEqual(set(Notification.select(Notification.item, Notification.user_id).tuples()), {(101, 42), (102, 43)})
        self.assertEqual(set(Blacklist.select(Blacklist.item, Blacklist.channel_id).tuples()), {(101, 1111)})
        lost = Filter.get_by_id(401)
        self.assertEqual((lost.method, lost.type, lost.enabled, lost.matches), ("legacy", "whitelist", False, 5))
        self.assertEqual((Filter.get_by_id(402).method, Filter.get_by_id(402).type, Filter.get_by_id(402).enabled),
                         ("regex", "whitelist", True))
        self.assertEqual((Filter.get_by_id(403).method, Filter.get_by_id(403).type), ("text", "blacklist"))
        self.assertEqual(Filter.select().count(), 3)

    def test_foreign_keys_are_valid_enforced_and_startup_is_idempotent(self):
        self.assertEqual(database.execute_sql("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(database.execute_sql("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(IntegrityError):
            Notification.create(item=999, user_id=1)
        database.close()
        create_tables()
        database.connect(reuse_if_open=True)
        self.assertEqual(Item.select().count(), 2)
        self.assertEqual(len(list(self.path.parent.glob(f"legacy.db.pre-v{SCHEMA_VERSION}.*.bak"))), 1)


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        configure_database(str(Path(self.directory.name) / "alerts.db"))
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(1111, "figure")
        self.alert = (await self.repository.list_alerts())[0]

    async def asyncTearDown(self):
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    async def rows(self, model):
        return await self.repository._call("test_inspect", lambda: list(model.select().order_by(model._meta.primary_key).dicts()))

    async def test_overlapping_alerts_keep_separate_change_baselines(self):
        await self.repository.register_alert(2222, "figure")
        second = next(row for row in await self.repository.list_alerts() if row["channel_id"] == 2222)
        first = listing()
        changed = replace(first, price=4000)
        self.assertEqual(await self.repository.observe(self.alert, first), "new")
        self.assertEqual(await self.repository.observe(second, first), "new")
        self.assertEqual(await self.repository.observe(self.alert, first), "unchanged")
        self.assertEqual(await self.repository.observe(self.alert, changed), "changed")
        self.assertEqual(await self.repository.observe(second, changed), "changed")
        self.assertEqual(await self.repository.observe(second, changed), "unchanged")
        self.assertEqual(len(await self.rows(Item)), 1)
        baselines = await self.rows(AlertItem)
        self.assertEqual([row["price"] for row in baselines], [4000, 4000])
        jobs = await self.repository.due_deliveries()
        self.assertEqual([row["destination_id"] for row in jobs], [1111, 2222, 1111, 2222])
        self.assertEqual([bool(json.loads(row["payload"])["differences"]) for row in jobs], [False, False, True, True])

    async def test_same_raw_identifier_from_different_sources_is_independent(self):
        yahoo, mercari = listing(), listing("mercari", price=3500)
        self.assertEqual(await self.repository.observe(self.alert, yahoo), "new")
        self.assertEqual(await self.repository.observe(self.alert, mercari), "new")
        self.assertEqual(await self.repository.observe(self.alert, yahoo), "unchanged")
        self.assertEqual(await self.repository.observe(self.alert, replace(mercari, price=2500)), "changed")
        items = await self.rows(Item)
        self.assertEqual([(row["checker"], row["item_id"], row["price"]) for row in items],
                         [("yahooauction", "same-id", 5000), ("mercari", "same-id", 2500)])
        self.assertEqual(len(await self.rows(AlertItem)), 2)
        self.assertEqual(len(await self.repository.due_deliveries()), 3)

    async def test_global_subscription_gets_one_dm_for_a_shared_listing_change(self):
        await self.repository.register_alert(2222, "other query")
        second = next(row for row in await self.repository.list_alerts() if row["channel_id"] == 2222)
        original = listing()
        await self.repository.observe(self.alert, original)
        await self.repository.observe(second, original)
        item_id = (await self.rows(Item))[0]["id"]
        self.assertTrue(await self.repository.subscribe(item_id, 99))
        self.assertFalse(await self.repository.subscribe(item_id, 99))
        await self.repository.observe(self.alert, replace(original, price=4000))
        await self.repository.observe(second, replace(original, price=4000))
        jobs = await self.repository.due_deliveries()
        self.assertEqual(len([row for row in jobs if row["kind"] == "dm"]), 1)
        self.assertEqual(len([row for row in jobs if row["kind"] == "channel"]), 4)

    async def test_enqueue_failure_rolls_back_global_fact_baseline_and_all_jobs(self):
        original = listing()
        await self.repository.observe(self.alert, original)
        item_id = (await self.rows(Item))[0]["id"]
        await self.repository.subscribe(item_id, 99)
        enqueue, calls = self.repository._enqueue, 0
        def fail_second_enqueue(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated outbox write failure")
            return enqueue(*args)
        with patch.object(self.repository, "_enqueue", side_effect=fail_second_enqueue):
            with self.assertRaisesRegex(RuntimeError, "outbox write failure"):
                await self.repository.observe(self.alert, replace(original, price=4000))
        self.assertEqual((await self.rows(Item))[0]["price"], 5000)
        self.assertEqual((await self.rows(AlertItem))[0]["price"], 5000)
        self.assertEqual(len(await self.rows(DeliveryJob)), 1)
        self.assertEqual(await self.repository.observe(self.alert, replace(original, price=4000)), "changed")
        self.assertEqual(len(await self.rows(DeliveryJob)), 3)
        self.assertEqual(self.metrics.registry.get_sample_value("auction_bot_database_errors_total", {"operation": "observe"}), 1)

    async def test_unregister_cancels_pending_jobs_and_stale_observation(self):
        await self.repository.observe(self.alert, listing())
        candidate = (await self.repository.due_deliveries())[0]
        self.assertTrue(await self.repository.unregister_alert(1111, "figure"))
        self.assertIsNone(await self.repository.begin_delivery(candidate["id"]))
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual((await self.rows(DeliveryJob))[0]["status"], "cancelled")
        self.assertEqual(await self.repository.observe(self.alert, replace(listing(), price=3000)), "unregistered")
        self.assertEqual(len(await self.rows(AlertItem)), 0)
        self.assertEqual((await self.rows(Item))[0]["price"], 5000)

    async def test_stale_results_cannot_write_to_a_reused_alert_id(self):
        await self.repository.unregister_alert(1111, "figure")
        await self.repository.register_alert(2222, "music")
        replacement = (await self.repository.list_alerts())[0]
        self.assertEqual(replacement["id"], self.alert["id"])
        self.assertEqual(await self.repository.observe(self.alert, listing()), "unregistered")
        self.assertEqual(await self.rows(AlertItem), [])
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual(await self.repository.observe(replacement, listing()), "new")
        self.assertEqual((await self.repository.due_deliveries())[0]["destination_id"], 2222)

    async def test_blacklist_is_channel_scoped_and_cancels_queued_channel_jobs(self):
        await self.repository.register_alert(2222, "figure")
        second = next(row for row in await self.repository.list_alerts() if row["channel_id"] == 2222)
        await self.repository.observe(self.alert, listing())
        await self.repository.observe(second, listing())
        item_id = (await self.rows(Item))[0]["id"]
        await self.repository.blacklist_item(item_id, 1111)
        await self.repository.blacklist_item(item_id, 1111)
        self.assertEqual(await self.repository.observe(self.alert, replace(listing(), price=4000)), "blacklisted")
        self.assertEqual(await self.repository.observe(second, replace(listing(), price=4000)), "changed")
        self.assertEqual([row["destination_id"] for row in await self.repository.due_deliveries()], [2222, 2222])
        self.assertEqual(len(await self.rows(Blacklist)), 1)

    async def test_unsubscribe_cancels_pending_dm_and_preserves_channel_delivery(self):
        await self.repository.observe(self.alert, listing())
        item_id = (await self.rows(Item))[0]["id"]
        await self.repository.subscribe(item_id, 99)
        await self.repository.observe(self.alert, replace(listing(), price=4000))
        dm = next(row for row in await self.repository.due_deliveries() if row["kind"] == "dm")
        self.assertTrue(await self.repository.unsubscribe(item_id, 99))
        self.assertFalse(await self.repository.unsubscribe(item_id, 99))
        self.assertIsNone(await self.repository.begin_delivery(dm["id"]))
        self.assertEqual([row["kind"] for row in await self.repository.due_deliveries()], ["channel", "channel"])

    async def test_unregister_cancels_failed_job_and_excludes_operational_requeue(self):
        await self.repository.observe(self.alert, listing())
        candidate = (await self.repository.due_deliveries())[0]
        await self.repository.fail_delivery(candidate["id"], "ForbiddenError", 0, permanent=True)
        self.assertEqual((await self.rows(DeliveryJob))[0]["status"], "failed")
        self.assertTrue(await self.repository.unregister_alert(1111, "figure"))
        job = (await self.rows(DeliveryJob))[0]
        self.assertEqual((job["status"], job["alert"]), ("cancelled", None))
        requeued = await self.repository._call("test_operational_requeue", lambda: DeliveryJob.update(status="pending").where(
            DeliveryJob.id == candidate["id"], DeliveryJob.status == "failed").execute())
        self.assertEqual(requeued, 0)
        self.assertIsNone(await self.repository.begin_delivery(candidate["id"]))
        self.assertEqual(await self.repository.due_deliveries(), [])

    async def test_blacklist_cancels_failed_channel_job(self):
        await self.repository.observe(self.alert, listing())
        candidate = (await self.repository.due_deliveries())[0]
        item_id = (await self.rows(Item))[0]["id"]
        await self.repository.fail_delivery(candidate["id"], "ForbiddenError", 0, permanent=True)
        await self.repository.blacklist_item(item_id, 1111)
        self.assertEqual((await self.rows(DeliveryJob))[0]["status"], "cancelled")
        self.assertEqual((await self.repository.stats())["failed"], 0)
        self.assertIsNone(await self.repository.begin_delivery(candidate["id"]))

    async def test_unsubscribe_cancels_failed_dm_and_keeps_failed_channel_job(self):
        await self.repository.observe(self.alert, listing())
        item_id = (await self.rows(Item))[0]["id"]
        await self.repository.subscribe(item_id, 99)
        await self.repository.observe(self.alert, replace(listing(), price=4000))
        jobs = await self.repository.due_deliveries()
        dm = next(row for row in jobs if row["kind"] == "dm")
        channel = next(row for row in jobs if row["kind"] == "channel")
        for job in (dm, channel):
            await self.repository.fail_delivery(job["id"], "ForbiddenError", 0, permanent=True)
        self.assertTrue(await self.repository.unsubscribe(item_id, 99))
        statuses = {row["id"]: row["status"] for row in await self.rows(DeliveryJob)}
        self.assertEqual((statuses[dm["id"]], statuses[channel["id"]]), ("cancelled", "failed"))
        self.assertIsNone(await self.repository.begin_delivery(dm["id"]))

    async def test_reconcile_sets_missing_servers_only(self):
        await self.repository.register_alert(2222, "figure", guild_id=7)
        await self.repository.register_alert(3333, "figure")
        updated = await self.repository.reconcile_guilds({1111: 5, 2222: 5, 4444: 5})
        servers = {row["channel_id"]: row["guild_id"] for row in await self.repository.list_alerts()}
        self.assertEqual(updated, 1)
        # An alert that already has a server keeps it; channels not in the mapping stay unknown.
        self.assertEqual(servers, {1111: 5, 2222: 7, 3333: None})
        self.assertEqual(await self.repository.reconcile_guilds({}), 0)


if __name__ == "__main__":
    unittest.main()
