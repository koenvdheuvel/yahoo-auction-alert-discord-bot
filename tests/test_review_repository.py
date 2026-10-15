"""Real SQLite history isolation, immutable version CAS and safe migrations."""
import asyncio
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from models import (ActiveReviewRules, Alert, AlertItem, CandidateFeedback,
                    CandidateObservation, DeliveryJob, Item, Message, REVIEW_TABLES,
                    ReviewRuleVersion, SCHEMA_VERSION, SchemaVersion, TABLES,
                    configure_database, create_tables, database, utcnow)
from observability import Metrics
from repositories import Repository
from review_repository import (ReviewConflict, ReviewNotFound, ReviewRepositoryMixin,
                               ReviewValidation)
from domain import Listing


class HistoryRepository(Repository, ReviewRepositoryMixin):
    pass


def facts(external_id="item", title="BＡＢＹＭＥＴＡＬ ベビーメタル CD", source="mercari"):
    return {"id": external_id, "source": source, "title": title, "stock": 1,
            "price": 2500, "buyout_price": 0, "image_url": "https://example.com/image",
            "url": "https://example.com/item", "end_time": None}


def decision(verdict="filtered", **fields):
    return {"verdict": verdict, "allowed": verdict == "accepted", "normalized_title": "babymetal ベビーメタル cd",
            "reasons": [{"code": "excluded", "message": "Accessory exclusion", "group_id": "accessories"}],
            "matched_groups": ["accessories"], "legacy_matched_rules": [], "normalization_version": 1,
            **fields}


class ReviewRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        configure_database(str(Path(self.directory.name) / "history.sqlite"))
        create_tables()
        self.repository = HistoryRepository(Metrics())
        await self.repository.start()
        self.channel = 123456789012345678
        self.guild = 234567890123456789
        await self.repository.register_alert(self.channel, "BABYMETAL", self.guild)
        self.alert = (await self.repository.list_alerts())[0]

    async def asyncTearDown(self):
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    async def rows(self, model):
        return await self.repository._call("test_history_rows", lambda: list(model.select().dicts()))

    async def archive(self, verdict="filtered", external_id="item", **kwargs):
        return await self.repository.archive_candidate(self.alert, facts(external_id), decision(verdict), **kwargs)

    async def test_filtered_history_preserves_facts_and_has_no_live_or_delivery_effects(self):
        identifier = await self.archive()
        page = await self.repository.list_candidates()
        row = page["items"][0]
        self.assertIsInstance(identifier, str)
        self.assertEqual((row["id"], row["alert_id"], row["alert_snapshot_id"]),
                         (identifier, str(self.alert["id"]), str(self.alert["id"])))
        self.assertEqual((row["channel_id"], row["guild_id"]), (str(self.channel), str(self.guild)))
        self.assertEqual(row["payload"], facts())
        self.assertEqual(row["decision"], decision())
        self.assertEqual(row["title"], facts()["title"])
        self.assertEqual(row["original_title"], row["title"])
        self.assertEqual(row["normalized_title"], decision()["normalized_title"])
        self.assertEqual(row["normalization_version"], 1)
        self.assertTrue(row["observed_at"].endswith("Z"))
        self.assertEqual((page["total"], page["has_more"], row["feedback"]), (1, False, None))
        for model in (Item, AlertItem, DeliveryJob, Message):
            self.assertEqual(await self.rows(model), [])
        summary = (await self.repository.review_alerts())[0]
        self.assertEqual((summary["id"], summary["archived_count"], summary["active_version_id"]),
                         (str(self.alert["id"]), 1, None))

    async def test_feedback_is_separate_upsert_and_can_be_cleared_without_changing_decision(self):
        identifier = await self.archive()
        first = await self.repository.set_candidate_feedback(identifier, "wrong_product")
        self.assertEqual(first["feedback"], "wrong_product")
        self.assertTrue(first["feedback_updated_at"].endswith("Z"))
        updated = await self.repository.set_candidate_feedback(identifier, "relevant")
        self.assertEqual(updated["feedback"], "relevant")
        self.assertEqual(updated["decision"], decision())
        self.assertEqual(len(await self.rows(CandidateFeedback)), 1)
        cleared = await self.repository.set_candidate_feedback(identifier, None)
        self.assertIsNone(cleared["feedback"])
        self.assertIsNone(cleared["feedback_updated_at"])
        self.assertEqual(await self.rows(CandidateFeedback), [])
        with self.assertRaises(ReviewValidation):
            await self.repository.set_candidate_feedback(identifier, "incorrect-label")
        with self.assertRaises(ReviewNotFound):
            await self.repository.set_candidate_feedback("99999", "unsure")

    async def test_pagination_search_source_verdict_feedback_and_replay_are_bounded(self):
        filtered = await self.archive(external_id="filtered")
        accepted = await self.archive("accepted", "accepted")
        await self.repository.archive_candidate(self.alert, facts("review", "Separate book", "surugaya"),
                                                decision("review", normalized_title="separate book"))
        await self.repository.set_candidate_feedback(filtered, "accessory")
        page = await self.repository.list_candidates(limit=2)
        self.assertEqual((page["total"], len(page["items"]), page["has_more"], page["next_offset"]), (3, 2, True, 2))
        final = await self.repository.list_candidates(limit=2, offset=2)
        self.assertEqual((len(final["items"]), final["has_more"], final["next_offset"]), (1, False, None))
        self.assertEqual((await self.repository.list_candidates(search="Separate"))["total"], 1)
        self.assertEqual((await self.repository.list_candidates(search="babymetal ベビーメタル"))["total"], 2)
        self.assertEqual((await self.repository.list_candidates(source="surugaya"))["total"], 1)
        self.assertEqual((await self.repository.list_candidates(verdict="accepted"))["items"][0]["id"], accepted)
        self.assertEqual((await self.repository.list_candidates(feedback="accessory"))["items"][0]["id"], filtered)
        self.assertEqual((await self.repository.list_candidates(feedback="unreviewed"))["total"], 2)
        self.assertEqual((await self.repository.review_candidates(str(self.alert["id"])))["total"], 3)
        for parameters in ({"limit": 501}, {"limit": 0}, {"offset": -1}, {"search": "x" * 257}, {"feedback": "bad"}):
            with self.subTest(parameters=parameters), self.assertRaises(ReviewValidation):
                await self.repository.list_candidates(**parameters)
        self.assertEqual(await self.rows(Item), [])
        self.assertEqual(await self.rows(DeliveryJob), [])

    async def test_versions_use_compare_and_swap_and_rollback_creates_a_new_copy(self):
        rules1, rules2 = {"aliases": ["ベビーメタル"]}, {"aliases": ["babymetal", "ベビーメタル"]}
        initial = await self.repository.get_review_rules(str(self.alert["id"]))
        self.assertIsNone(initial["active_version"])
        first = await self.repository.publish_review_rules(self.alert["id"], rules1, None)
        with self.assertRaises(ReviewConflict):
            await self.repository.publish_review_rules(self.alert["id"], rules2, None)
        second = await self.repository.publish_review_rules(self.alert["id"], rules2, first["id"])
        with self.assertRaises(ReviewConflict):
            await self.repository.activate_review_version(self.alert["id"], first["id"], first["id"])
        third = await self.repository.activate_review_version(str(self.alert["id"]), first["id"], second["id"])
        self.assertEqual((first["version"], second["version"], third["version"]), (1, 2, 3))
        self.assertEqual(third["ruleset"], rules1)
        self.assertEqual(third["restored_from_version_id"], first["id"])
        self.assertNotEqual(third["id"], first["id"])
        current = await self.repository.get_review_rules(self.alert["id"])
        self.assertEqual(current["active_version"], third)
        self.assertEqual(current["versions_total"], 3)
        self.assertEqual([version["ruleset"] for version in current["versions"]], [rules1, rules2, rules1])
        self.assertEqual((await self.repository.active_rules_for_alert(self.alert))["id"], third["id"])
        self.assertEqual((await self.repository.review_alerts())[0]["active_version_id"], third["id"])
        self.assertEqual(await self.rows(DeliveryJob), [])

    async def test_concurrent_drafts_cannot_both_publish_against_the_same_version(self):
        first = await self.repository.publish_review_rules(self.alert["id"], {"groups": []})
        results = await asyncio.gather(
            self.repository.publish_review_rules(self.alert["id"], {"groups": ["first"]}, first["id"]),
            self.repository.publish_review_rules(self.alert["id"], {"groups": ["second"]}, first["id"]),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(result, ReviewConflict) for result in results), 1)
        self.assertEqual((await self.repository.get_review_rules(self.alert["id"]))["versions_total"], 2)

    async def test_bounded_version_listing_retains_older_versions_for_explicit_restore(self):
        first = await self.repository.publish_review_rules(self.alert["id"], {"value": "first"})
        current = first
        for index in range(34):
            current = await self.repository.publish_review_rules(self.alert["id"], {"value": index}, current["id"])
        state = await self.repository.get_review_rules(self.alert["id"])
        self.assertEqual(state["versions_total"], 35)
        self.assertLessEqual(len(state["versions"]), 30)
        self.assertEqual(state["active_version"]["id"], current["id"])
        self.assertNotIn(first["id"], {version["id"] for version in state["versions"]})
        restored = await self.repository.activate_review_version(self.alert["id"], first["id"], current["id"])
        self.assertEqual(restored["ruleset"], first["ruleset"])
        self.assertEqual(restored["version"], 36)

    async def test_history_and_feedback_survive_unregister_and_cannot_follow_reused_alert_ids(self):
        version = await self.repository.publish_review_rules(self.alert["id"], {"groups": []})
        identifier = await self.archive(ruleset_version_id=version["id"])
        await self.repository.set_candidate_feedback(identifier, "bundle")
        await self.repository.unregister_alert(self.channel, self.alert["search_query"])
        row = (await self.repository.list_candidates())["items"][0]
        self.assertIsNone(row["alert_id"])
        self.assertEqual(row["alert_snapshot_id"], str(self.alert["id"]))
        self.assertEqual(row["feedback"], "bundle")
        self.assertEqual(row["ruleset_version_id"], version["id"])
        self.assertEqual(await self.rows(ActiveReviewRules), [])
        self.assertIsNone((await self.rows(ReviewRuleVersion))[0]["alert"])
        await self.repository.register_alert(333333333333333333, "different")
        replacement = (await self.repository.list_alerts())[0]
        self.assertEqual(replacement["id"], self.alert["id"])
        self.assertIsNone(await self.repository.active_rules_for_alert(self.alert))
        self.assertIsNone(await self.repository.active_rules_for_alert(replacement))
        self.assertEqual((await self.repository.review_candidates(replacement["id"]))["total"], 0)
        stale = await self.archive("review", "late-result", ruleset_version_id=version["id"])
        stale_row = next(row for row in (await self.repository.list_candidates())["items"] if row["id"] == stale)
        self.assertIsNone(stale_row["alert_id"])
        with self.assertRaises(ReviewNotFound):
            await self.repository.activate_review_version(replacement["id"], version["id"], None)
        new_version = await self.repository.publish_review_rules(replacement["id"], {"groups": ["new"]})
        self.assertEqual(new_version["version"], 1)

    async def test_partial_invalid_payload_is_archived_without_creating_a_live_listing(self):
        identifier = await self.repository.archive_candidate(self.alert, {"source": "mercari", "title": "broken"},
            decision("review", observation_kind="invalid", reasons=[{"code": "invalid", "message": "Missing price"}]))
        row = (await self.repository.list_candidates())["items"][0]
        self.assertEqual((row["id"], row["external_id"], row["observation_kind"]), (identifier, "", "invalid"))
        self.assertEqual(row["payload"], {"source": "mercari", "title": "broken"})
        self.assertEqual(await self.rows(Item), [])
        self.assertEqual(await self.rows(DeliveryJob), [])

    async def test_archived_version_disambiguates_identical_reused_alert_identity(self):
        version = await self.repository.publish_review_rules(self.alert["id"], {"value": "original"})
        await self.repository.unregister_alert(self.channel, self.alert["search_query"])
        await self.repository.register_alert(self.channel, self.alert["search_query"], self.guild)
        replacement = (await self.repository.list_alerts())[0]
        self.assertEqual(replacement, self.alert)
        identifier = await self.archive(ruleset_version_id=version["id"])
        row = (await self.repository.list_candidates())["items"][0]
        self.assertEqual(row["id"], identifier)
        self.assertIsNone(row["alert_id"])
        self.assertEqual(row["ruleset_version_id"], version["id"])
        self.assertEqual((await self.repository.review_candidates(replacement["id"]))["total"], 0)

    async def test_archive_participates_in_outer_transaction_and_rejects_other_alert_rules(self):
        await self.repository.register_alert(444444444444444444, "other")
        other = next(row for row in await self.repository.list_alerts() if row["id"] != self.alert["id"])
        version = await self.repository.publish_review_rules(other["id"], {"groups": []})
        with self.assertRaises(ReviewValidation):
            await self.archive(ruleset_version_id=version["id"])
        def rollback():
            with database.atomic():
                self.repository._archive_candidate_sync(self.alert, facts(), decision())
                raise RuntimeError("later live outbox write failed")
        with self.assertRaisesRegex(RuntimeError, "outbox write failed"):
            await self.repository._call("test_archive_rollback", rollback)
        self.assertEqual((await self.repository.list_candidates())["total"], 0)

    async def test_live_accepted_fact_history_and_outbox_commit_or_roll_back_together(self):
        item = Listing("accepted", "mercari", "Original title", 1, 2500)
        with patch.object(self.repository, "_enqueue", side_effect=RuntimeError("outbox unavailable")):
            with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
                await self.repository.observe(self.alert, item, decision_payload=decision("accepted"))
        for model in (Item, AlertItem, DeliveryJob, CandidateObservation):
            self.assertEqual(await self.rows(model), [])
        self.assertEqual(await self.repository.observe(self.alert, item, decision_payload=decision("accepted")), "new")
        for model in (Item, AlertItem, DeliveryJob, CandidateObservation):
            self.assertEqual(len(await self.rows(model)), 1)

    async def test_accepted_long_urls_bound_archive_without_altering_facts_jobs_or_siblings(self):
        from filtering import default_ruleset
        from review_service import ReviewService

        long_id = "identity-" + "x" * 400
        long_url = "https://example.com/" + "長" * 150000
        long_image = "https://example.com/" + "i" * 6000
        item = Listing(long_id, "mercari", "Original title", 1, 2500,
                       image_url=long_image, url=long_url)
        recorded = decision("accepted", normalized_title="original title")
        self.assertEqual(await self.repository.observe(self.alert, item, decision_payload=recorded), "new")
        sibling = Listing("sibling", "mercari", "Sibling title", 1, 3000, url="https://example.com/sibling")
        self.assertEqual(await self.repository.observe(self.alert, sibling, decision_payload=recorded), "new")
        rows = (await self.repository.list_candidates())["items"]
        snapshot = next(row for row in rows if row["title"] == item.title)
        self.assertEqual(snapshot["verdict"], "accepted")
        self.assertEqual(snapshot["decision"], recorded)
        self.assertTrue(snapshot["incomplete"])
        self.assertTrue(snapshot["payload"]["archive_truncated"])
        self.assertEqual(snapshot["external_id"], long_id[:256])
        self.assertEqual(snapshot["payload"]["original_identity"]["id"], long_id)
        self.assertEqual(snapshot["payload"]["url"], long_url[:4096])
        self.assertEqual(snapshot["payload"]["image_url"], long_image[:4096])
        self.assertLessEqual(len(json.dumps(snapshot["payload"], ensure_ascii=False).encode()), 128 * 1024)
        stored = next(row for row in await self.rows(Item) if row["item_id"] == long_id)
        self.assertEqual((stored["url"], stored["image_url"]), (long_url, long_image))
        jobs = await self.rows(DeliveryJob)
        self.assertEqual(len(jobs), 2)
        delivered_facts = json.loads(jobs[0]["payload"])["listing"]
        self.assertEqual((delivered_facts["id"], delivered_facts["url"], delivered_facts["image_url"]),
                         (long_id, long_url, long_image))
        self.assertEqual((item.id, item.url, item.image_url), (long_id, long_url, long_image))
        result = ReviewService._replay([snapshot], default_ruleset(), default_ruleset(), [])
        self.assertEqual(result["items"][0]["original_decision"]["verdict"], "accepted")
        self.assertEqual(result["items"][0]["draft_decision"]["verdict"], "review")
        self.assertEqual(await self.rows(DeliveryJob), jobs)

    async def test_pruning_is_bounded_removes_feedback_and_never_reuses_candidate_ids(self):
        ids = [await self.archive(external_id=str(index)) for index in range(4)]
        await self.repository.set_candidate_feedback(ids[0], "unsure")
        await self.repository._call("test_backdate", lambda: CandidateObservation.update(
            observed_at=utcnow() - timedelta(days=91)).where(CandidateObservation.id.in_(ids[:2])).execute())
        first = await self.repository.prune_candidates(limit=1)
        self.assertEqual((first["deleted"], first["remaining"], first["has_more"]), (1, 3, True))
        self.assertEqual(await self.rows(CandidateFeedback), [])
        second = await self.repository.prune_candidates(max_rows=1, limit=1000)
        self.assertEqual((second["deleted"], second["remaining"], second["has_more"]), (2, 1, False))
        await self.repository.prune_candidates(max_rows=0)
        next_id = await self.archive()
        self.assertGreater(int(next_id), max(map(int, ids)))
        self.assertEqual(await self.rows(Item), [])
        with self.assertRaises(ReviewValidation):
            await self.repository.prune_candidates(limit=1001)

    async def test_history_import_is_explicit_bounded_idempotent_and_marked_incomplete(self):
        listing = Listing("external", "mercari", "ＢＡＢＹＭＥＴＡＬ　 ＣＤ", 1, 2000)
        await self.repository.observe(self.alert, listing)
        self.assertEqual((await self.repository.list_candidates())["total"], 0)
        result = await self.repository.bootstrap_history(limit=1)
        self.assertEqual((result["imported"], result["incomplete"], result["truncated"]), (1, 1, True))
        before = await self.rows(DeliveryJob)
        complete = await self.repository.bootstrap_history(limit=1000)
        self.assertEqual(complete["imported"], 1)
        self.assertEqual(complete["skipped"], 1)
        repeated = await self.repository.bootstrap_history()
        self.assertEqual((repeated["imported"], repeated["skipped"]), (0, 2))
        rows = (await self.repository.list_candidates())["items"]
        self.assertEqual({row["origin"] for row in rows}, {"delivery_import", "item_import"})
        self.assertTrue(all(row["incomplete"] and row["verdict"] == "review" for row in rows))
        self.assertTrue(all(row["normalization_version"] == 1 and row["normalized_title"] == "babymetal cd" for row in rows))
        self.assertEqual(await self.rows(DeliveryJob), before)
        self.assertEqual(len(await self.rows(Item)), 1)

    async def test_bounded_json_and_title_metadata_are_explicit(self):
        huge_title = facts(title="x" * 140000)
        await self.repository.archive_candidate(self.alert, huge_title, decision())
        huge_row = (await self.repository.list_candidates())["items"][0]
        self.assertEqual(len(huge_row["payload"]["title"]), 10000)
        self.assertTrue(huge_row["payload"]["archive_truncated"])
        self.assertTrue(huge_row["incomplete"])
        self.assertEqual(len(huge_title["title"]), 140000)
        with self.assertRaises(ReviewValidation):
            await self.repository.publish_review_rules(self.alert["id"], {"nan": float("nan")})
        await self.repository.archive_candidate(self.alert, facts(title="x" * 10001), decision())
        row = (await self.repository.list_candidates())["items"][0]
        self.assertEqual(len(row["title"]), 10000)
        self.assertEqual(len(row["payload"]["title"]), 10000)
        self.assertTrue(row["incomplete"])
        await self.repository.archive_candidate(self.alert, {**facts(), "archive_truncated": True}, decision())
        self.assertTrue((await self.repository.list_candidates())["items"][0]["incomplete"])

    async def test_large_archive_extras_and_identity_keep_bounded_provenance(self):
        identifier = "長" * 5000
        payload = {**facts(external_id=identifier), "notes": "n" * 150000}
        await self.repository.archive_candidate(self.alert, payload, decision("accepted"))
        row = (await self.repository.list_candidates())["items"][0]
        snapshot = row["payload"]
        self.assertLessEqual(len(json.dumps(snapshot, ensure_ascii=False).encode()), 128 * 1024)
        self.assertTrue(snapshot["archive_truncated"])
        self.assertEqual(row["verdict"], "accepted")
        self.assertEqual(row["external_id"], identifier[:256])
        self.assertNotIn("id", snapshot["original_identity"])
        self.assertEqual(snapshot["original_identity"], {
            "length": len(identifier), "sha256": hashlib.sha256(identifier.encode()).hexdigest()})
        self.assertIn("notes", snapshot["archive_omitted_fields"])
        self.assertEqual(payload["notes"], "n" * 150000)


class ReviewMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "v2.sqlite"
        configure_database(str(self.path))
        database.connect()
        legacy_tables = [model for model in TABLES if model not in REVIEW_TABLES]
        database.create_tables(legacy_tables)
        alert = Alert.create(channel_id=123, guild_id=456, search_query="old")
        item = Item.create(item_id="old", checker="mercari", title="Old title", price=3000)
        AlertItem.create(alert=alert, item=item, stock=1, price=3000, buyout_price=0)
        Message.create(message_id=999, alert=alert, item=item, channel_id=123)
        DeliveryJob.create(alert=alert, item=item, kind="channel", destination_id=123,
                           payload=json.dumps({"listing": facts()}), status="pending", attempts=2, message_id=999)
        SchemaVersion.create(id=1, version=2)
        database.close()
        with sqlite3.connect(self.path) as connection:
            self.before = {name: connection.execute(f'SELECT * FROM "{name}"').fetchall()
                           for name in ("alert", "item", "alert_item", "message", "delivery_job")}

    def tearDown(self):
        database.close()
        self.directory.cleanup()

    def test_v2_migration_is_additive_backed_up_and_idempotent(self):
        create_tables()
        with sqlite3.connect(self.path) as connection:
            after = {name: connection.execute(f'SELECT * FROM "{name}"').fetchall() for name in self.before}
            self.assertEqual(after, self.before)
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({model._meta.table_name for model in REVIEW_TABLES}.issubset(tables))
        backups = list(self.path.parent.glob(f"v2.sqlite.pre-v{SCHEMA_VERSION}.*.bak"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT * FROM delivery_job").fetchall(), self.before["delivery_job"])
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='candidate_observation'").fetchone())
        create_tables()
        self.assertEqual(list(self.path.parent.glob("*.bak")), backups)

    def test_failed_additive_migration_rolls_back_schema_version_and_new_tables(self):
        original = database.create_tables
        def fail_after_creating(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated review table migration failure")
        with patch.object(database, "create_tables", side_effect=fail_after_creating):
            with self.assertRaisesRegex(RuntimeError, "migration failure"):
                create_tables()
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], 2)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='candidate_observation'").fetchone())
            self.assertEqual(connection.execute("SELECT * FROM delivery_job").fetchall(), self.before["delivery_job"])
        self.assertEqual(len(list(self.path.parent.glob("*.bak"))), 1)
