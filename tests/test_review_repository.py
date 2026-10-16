"""Real SQLite history isolation, immutable version CAS and safe migrations."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from filtering import default_ruleset
from models import (ActiveReviewRules, Alert, AlertItem, CandidateFeedback,
                    CandidateObservation, DeliveryJob, Filter, Item, Message, Notification, REVIEW_TABLES,
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


def snowflake(moment, sequence=0):
    """A Discord message ID created at `moment`."""
    return ((int(moment.timestamp() * 1000) - 1420070400000) << 22) + sequence


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
        summary = (await self.repository.review_alerts())["alerts"][0]
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
        self.assertEqual((await self.repository.list_candidates(alert_id=str(self.alert["id"])))["total"], 3)
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
        self.assertEqual((await self.repository.review_alerts())["alerts"][0]["active_version_id"], third["id"])
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
        self.assertEqual((await self.repository.list_candidates(alert_id=replacement["id"]))["total"], 0)
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
        self.assertEqual((await self.repository.list_candidates(alert_id=replacement["id"]))["total"], 0)

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

    async def test_pruning_removes_least_recently_seen_unlabeled_rows_and_never_reuses_ids(self):
        ids = [await self.archive(external_id=str(index)) for index in range(5)]
        await self.repository.set_candidate_feedback(ids[0], "accessory")

        def backdate():
            for index, days in ((0, 120), (1, 100), (2, 91)):
                CandidateObservation.update(observed_at=utcnow() - timedelta(days=days),
                                            last_seen_at=utcnow() - timedelta(days=days)).where(
                    CandidateObservation.id == ids[index]).execute()
            # First seen long ago but still in the search results: not old.
            CandidateObservation.update(observed_at=utcnow() - timedelta(days=200)).where(
                CandidateObservation.id == ids[3]).execute()
        await self.repository._call("test_backdate", backdate)
        first = await self.repository.prune_candidates(limit=1)
        self.assertEqual((first["deleted"], first["remaining"], first["has_more"]), (1, 4, True))
        second = await self.repository.prune_candidates()
        self.assertEqual((second["deleted"], second["remaining"], second["has_more"]), (1, 3, False))
        remaining = {row["id"] for row in await self.rows(CandidateObservation)}
        self.assertEqual(remaining, {int(ids[0]), int(ids[3]), int(ids[4])})
        self.assertEqual([row["label"] for row in await self.rows(CandidateFeedback)], ["accessory"])
        third = await self.repository.prune_candidates(max_rows=1)
        self.assertEqual((third["deleted"], third["remaining"], third["has_more"]), (2, 1, False))
        # Only the labeled row is left, so a cap below it removes nothing and reports no backlog.
        fourth = await self.repository.prune_candidates(max_rows=0)
        self.assertEqual((fourth["deleted"], fourth["remaining"], fourth["has_more"]), (0, 1, False))
        await self.repository.set_candidate_feedback(ids[0], None)
        self.assertEqual((await self.repository.prune_candidates(max_rows=0))["deleted"], 1)
        next_id = await self.archive()
        self.assertGreater(int(next_id), max(map(int, ids)))
        self.assertEqual(await self.rows(Item), [])
        with self.assertRaises(ReviewValidation):
            await self.repository.prune_candidates(limit=1001)

    async def test_history_import_is_explicit_bounded_idempotent_and_marked_incomplete(self):
        for external_id in ("posted", "tracked"):
            await self.repository.observe(self.alert, Listing(external_id, "mercari", "ＢＡＢＹＭＥＴＡＬ　 ＣＤ", 1, 2000))

        def keep_one_copy_each():
            # One listing is left only as a posted message, the other only as a tracked item.
            AlertItem.delete().where(AlertItem.item.in_(Item.select(Item.id).where(Item.item_id == "posted"))).execute()
            DeliveryJob.delete().where(DeliveryJob.item.in_(Item.select(Item.id).where(Item.item_id == "tracked"))).execute()
        await self.repository._call("test_keep_one_copy_each", keep_one_copy_each)
        self.assertEqual((await self.repository.list_candidates())["total"], 0)
        result = await self.repository.bootstrap_history(limit=1)
        self.assertEqual((result["imported"], result["incomplete"], result["truncated"]), (1, 1, True))
        before = await self.rows(DeliveryJob)
        complete = await self.repository.bootstrap_history(limit=1000)
        self.assertEqual((complete["imported"], complete["skipped"]), (1, 1))
        repeated = await self.repository.bootstrap_history()
        self.assertEqual((repeated["imported"], repeated["skipped"]), (0, 2))
        rows = (await self.repository.list_candidates())["items"]
        self.assertEqual({row["origin"] for row in rows}, {"delivery_import", "item_import"})
        self.assertTrue(all(row["incomplete"] and row["verdict"] == "review" for row in rows))
        self.assertTrue(all(row["normalization_version"] == 1 and row["normalized_title"] == "babymetal cd" for row in rows))
        self.assertEqual(await self.rows(DeliveryJob), before)
        self.assertEqual(len(await self.rows(Item)), 2)

    async def test_history_import_skips_listings_the_search_already_has(self):
        # The bot already saved this listing with its decision. It was also posted and is still tracked.
        await self.archive("accepted", external_id="seen")
        await self.repository.observe(self.alert, Listing("seen", "mercari", "BABYMETAL CD", 1, 2000))
        result = await self.repository.bootstrap_history()
        self.assertEqual((result["imported"], result["skipped"]), (0, 2))
        latest = await self.repository.list_candidates(self.alert["id"], latest=True)
        self.assertEqual([(row["origin"], row["verdict"]) for row in latest["items"]], [("live", "accepted")])

    async def add_posts(self, *posts):
        """Create listings with a Discord post each: (message ID, external ID, alert ID, options)."""
        def create():
            items = {}
            for message_id, external_id, alert_id, options in posts:
                items[external_id] = Item.create(item_id=external_id, checker="mercari",
                                                 title=f"BABYMETAL {external_id}", price=3000)
                Message.create(message_id=message_id, item=items[external_id], alert=alert_id,
                               channel_id=options.get("channel", self.channel), deleted=options.get("deleted", False))
                if options.get("subscribed"):
                    Notification.create(item=items[external_id], user_id=77)
            return {name: item.id for name, item in items.items()}
        return await self.repository._call("test_add_posts", create)

    async def test_removable_posts_are_the_search_live_posts_by_discord_age(self):
        await self.repository.register_alert(self.channel, "BABYMETAL shirt", self.guild)
        other = next(alert for alert in await self.repository.list_alerts() if alert["search_query"] == "BABYMETAL shirt")
        now = datetime.now(timezone.utc)
        recent, older, old, gone, others, elsewhere, orphan = (
            snowflake(now - timedelta(days=days), index) for index, days in enumerate((1, 3, 60, 2, 2, 2, 2)))
        items = await self.add_posts(
            (recent, "recent", self.alert["id"], {"subscribed": True}), (older, "older", self.alert["id"], {}),
            (old, "old", self.alert["id"], {}), (gone, "gone", self.alert["id"], {"deleted": True}),
            (others, "others", other["id"], {}), (elsewhere, "elsewhere", self.alert["id"], {"channel": 999}),
            (orphan, "orphan", None, {}))
        await self.repository._call("test_queue", lambda: DeliveryJob.create(
            item=items["older"], alert=self.alert["id"], kind="delete", destination_id=self.channel,
            message_id=older, payload="{}"))
        month = await self.repository.removable_posts(self.alert["id"], 30)
        self.assertEqual([post["message_id"] for post in month["posts"]], [recent, older])
        self.assertEqual(month["total"], 2)
        self.assertEqual([(post["subscribed"], post["queued"]) for post in month["posts"]], [(True, False), (False, True)])
        self.assertEqual(month["posts"][0]["listing"]["title"], "BABYMETAL recent")
        # Ages come from the message ID, not from when the row was saved.
        posted = datetime.fromisoformat(month["posts"][0]["posted_at"].replace("Z", "+00:00"))
        self.assertLess(abs(posted - (now - timedelta(days=1))), timedelta(seconds=1))
        everything = await self.repository.removable_posts(self.alert["id"])
        self.assertEqual([post["message_id"] for post in everything["posts"]], [recent, older, old])
        self.assertIsNone(everything["active_version"])
        with self.assertRaises(ReviewValidation):
            await self.repository.removable_posts(self.alert["id"], 14)

    async def test_queue_post_removals_needs_the_published_version_and_cancels_queued_posts(self):
        now = datetime.now(timezone.utc)
        live, subscribed, gone = (snowflake(now - timedelta(hours=hours)) for hours in (1, 2, 3))
        items = await self.add_posts((live, "live", self.alert["id"], {}),
                                     (subscribed, "subscribed", self.alert["id"], {"subscribed": True}),
                                     (gone, "gone", self.alert["id"], {"deleted": True}))
        # An update post of the live listing that has not gone out yet.
        await self.repository._call("test_queue", lambda: DeliveryJob.create(
            item=items["live"], alert=self.alert["id"], kind="channel", destination_id=self.channel, payload="{}"))
        self.assertEqual(await self.repository.post_removal_status(self.alert["id"]), {"run": None})
        with self.assertRaises(ReviewConflict):
            await self.repository.queue_post_removals(self.alert["id"], 1, [live])
        version = int((await self.repository.publish_review_rules(self.alert["id"], default_ruleset(), None))["id"])
        with self.assertRaises(ReviewConflict):
            await self.repository.queue_post_removals(self.alert["id"], version + 1, [live])
        self.assertEqual(await self.repository.queue_post_removals(self.alert["id"], version, [live, subscribed, gone]), 1)
        self.assertEqual(await self.repository.queue_post_removals(self.alert["id"], version, [live]), 0)
        jobs = await self.rows(DeliveryJob)
        removal = next(job for job in jobs if job["kind"] == "delete")
        self.assertEqual((removal["message_id"], removal["destination_id"], removal["status"]), (live, self.channel, "pending"))
        self.assertEqual(json.loads(removal["payload"]), {"version_id": str(version)})
        self.assertEqual(next(job for job in jobs if job["kind"] == "channel")["status"], "cancelled")
        run = (await self.repository.post_removal_status(self.alert["id"]))["run"]
        self.assertEqual((run["total"], run["pending"], run["removed"], run["failed"]), (1, 1, 0, 0))

    async def test_post_removal_is_limited_to_the_servers_given(self):
        live = snowflake(datetime.now(timezone.utc) - timedelta(hours=1))
        await self.add_posts((live, "live", self.alert["id"], {}))
        version = int((await self.repository.publish_review_rules(self.alert["id"], default_ruleset(), None))["id"])
        other_server = frozenset({self.guild + 1})
        # Another server's search answers exactly like a missing one, and nothing is queued.
        for call in (lambda: self.repository.removable_posts(self.alert["id"], 30, guilds=other_server),
                     lambda: self.repository.queue_post_removals(self.alert["id"], version, [live], guilds=other_server),
                     lambda: self.repository.post_removal_status(self.alert["id"], guilds=other_server)):
            with self.assertRaisesRegex(ReviewNotFound, "Alert no longer exists"):
                await call()
        self.assertEqual([job for job in await self.rows(DeliveryJob) if job["kind"] == "delete"], [])
        own = frozenset({self.guild})
        self.assertEqual([post["message_id"] for post in
                          (await self.repository.removable_posts(self.alert["id"], 30, guilds=own))["posts"]], [live])
        self.assertEqual(await self.repository.queue_post_removals(self.alert["id"], version, [live], guilds=own), 1)
        self.assertEqual((await self.repository.post_removal_status(self.alert["id"], guilds=own))["run"]["total"], 1)

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

    async def test_repeat_sightings_refresh_one_row_and_a_new_decision_adds_a_row_with_the_label(self):
        first = await self.archive("accepted", "listing")
        await self.repository.set_candidate_feedback(first, "relevant")
        before = (await self.rows(CandidateObservation))[0]
        version = await self.repository.publish_review_rules(self.alert["id"], {"groups": []})
        repeat = await self.repository.archive_candidate(
            self.alert, {**facts("listing"), "price": 2400}, decision("accepted"), version["id"])
        self.assertEqual(repeat, first)
        after = (await self.rows(CandidateObservation))[0]
        self.assertEqual(after["observed_at"], before["observed_at"])
        self.assertGreater(after["last_seen_at"], before["last_seen_at"])
        self.assertEqual(json.loads(after["payload"])["price"], 2400)
        self.assertEqual(after["ruleset_version"], int(version["id"]))
        # A different decision is history worth keeping: it gets its own row and keeps the label.
        changed = await self.archive("filtered", "listing")
        self.assertNotEqual(changed, first)
        rows = (await self.repository.list_candidates())["items"]
        self.assertEqual([(row["id"], row["feedback"]) for row in rows], [(changed, "relevant"), (first, "relevant")])
        latest = (await self.repository.list_candidates(latest=True))["items"]
        self.assertEqual([row["id"] for row in latest], [changed])
        # Other listings and rows without a listing ID are never merged.
        await self.archive("filtered", "other")
        for _ in range(2):
            await self.repository.archive_candidate(self.alert, {"source": "mercari", "title": "no id"},
                                                    decision("review", observation_kind="invalid"))
        self.assertEqual(len(await self.rows(CandidateObservation)), 5)
        self.assertEqual((await self.repository.list_candidates(latest=True))["total"], 4)

    async def test_accepted_listing_seen_again_by_polling_keeps_one_archive_row(self):
        listing = Listing("again", "mercari", "Original title", 1, 2500)
        recorded = decision("accepted", normalized_title="original title")
        self.assertEqual(await self.repository.observe(self.alert, listing, decision_payload=recorded), "new")
        self.assertEqual(await self.repository.observe(self.alert, listing, decision_payload=recorded), "unchanged")
        cheaper = Listing("again", "mercari", "Original title", 1, 1500)
        self.assertEqual(await self.repository.observe(self.alert, cheaper, decision_payload=recorded), "changed")
        rows = await self.rows(CandidateObservation)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["payload"])["price"], 1500)
        self.assertEqual(len(await self.rows(DeliveryJob)), 2)

    async def test_cursor_pages_neither_skip_nor_repeat_rows_while_labeling_and_polling(self):
        ids = [await self.archive(external_id=f"item-{index}") for index in range(5)]
        first = await self.repository.list_candidates(feedback="unlabeled", limit=2)
        self.assertEqual([row["id"] for row in first["items"]], [ids[4], ids[3]])
        for row in first["items"]:
            await self.repository.set_candidate_feedback(row["id"], "bundle")
        await self.archive(external_id="arrived-later")
        second = await self.repository.list_candidates(feedback="unlabeled", limit=2, cursor=first["next_cursor"])
        self.assertEqual(([row["id"] for row in second["items"]], second["next_offset"]), ([ids[2], ids[1]], None))
        third = await self.repository.list_candidates(feedback="unlabeled", limit=2, cursor=second["next_cursor"])
        self.assertEqual(([row["id"] for row in third["items"]], third["has_more"], third["next_cursor"]),
                         ([ids[0]], False, None))
        for cursor in ("", "x" * 129, "not base64!", "YmFk", "MjAyNi0xMC0xNnwx"):
            with self.subTest(cursor=cursor), self.assertRaises(ReviewValidation):
                await self.repository.list_candidates(cursor=cursor)

    async def test_facets_count_each_value_with_the_other_filters_applied(self):
        await self.archive("accepted", "a")
        filtered = await self.archive("filtered", "b")
        await self.archive("review", "c")
        await self.repository.set_candidate_feedback(filtered, "accessory")
        page = await self.repository.list_candidates(verdict="filtered", facets=True)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["facets"]["verdict"], {"accepted": 1, "filtered": 1, "review": 1})
        self.assertEqual(page["facets"]["feedback"], {"unlabeled": 0, "accessory": 1, "bundle": 0, "relevant": 0,
                                                      "unsure": 0, "wrong_product": 0})
        unlabeled = await self.repository.list_candidates(feedback="unlabeled", facets=True)
        self.assertEqual(unlabeled["facets"]["verdict"], {"accepted": 1, "filtered": 0, "review": 1})
        self.assertNotIn("facets", await self.repository.list_candidates())

    async def test_bulk_feedback_labels_existing_rows_and_reports_missing_ones(self):
        first, second = await self.archive(external_id="a"), await self.archive(external_id="b")
        result = await self.repository.set_candidates_feedback([first, second, "99999", first], "wrong_product")
        self.assertEqual([row["id"] for row in result["items"]], [first, second])
        self.assertEqual({row["feedback"] for row in result["items"]}, {"wrong_product"})
        self.assertEqual(result["missing"], ["99999"])
        cleared = await self.repository.set_candidates_feedback([first], None)
        self.assertIsNone(cleared["items"][0]["feedback"])
        self.assertEqual(len(await self.rows(CandidateFeedback)), 1)
        for ids, label in (([], "bundle"), (["1"] * 201, "bundle"), ("1", "bundle"), ([first], "bad"), ([True], None)):
            with self.subTest(ids=str(ids)[:20], label=label), self.assertRaises(ReviewValidation):
                await self.repository.set_candidates_feedback(ids, label)

    async def test_replay_sample_uses_latest_decisions_and_adds_labeled_listings_beyond_it(self):
        await self.repository.set_candidate_feedback(await self.archive("accepted", "old-labeled"), "wrong_product")
        await self.repository.set_candidate_feedback(await self.archive("accepted", "old-unsure"), "unsure")
        for index in range(3):
            await self.archive("accepted", f"recent-{index}")
        await self.archive("filtered", "recent-2")
        result = await self.repository.replay_candidates(self.alert["id"], limit=2, labeled_limit=10)
        self.assertEqual((result["available"], result["recent"], result["labeled_extra"]), (5, 2, 1))
        self.assertEqual([(row["external_id"], row["verdict"]) for row in result["items"]],
                         [("recent-2", "filtered"), ("recent-1", "accepted"), ("old-labeled", "accepted")])
        none_extra = await self.repository.replay_candidates(self.alert["id"], limit=2, labeled_limit=0)
        self.assertEqual(len(none_extra["items"]), 2)

    async def test_alert_summaries_count_latest_decisions_and_unassigned_history(self):
        await self.archive("accepted", "a")
        await self.archive("filtered", "a")
        await self.repository.set_candidate_feedback(await self.archive("review", "b"), "bundle")
        await self.repository.register_alert(555555555555555555, "detached")
        other = next(row for row in await self.repository.list_alerts() if row["search_query"] == "detached")
        await self.repository.archive_candidate(other, facts("x"), decision())
        await self.repository.unregister_alert(555555555555555555, "detached")
        result = await self.repository.review_alerts()
        summary = result["alerts"][0]
        self.assertEqual({key: summary[key] for key in (
            "archived_count", "listing_count", "accepted_count", "filtered_count", "review_count", "labeled_count")},
            {"archived_count": 3, "listing_count": 2, "accepted_count": 0, "filtered_count": 1,
             "review_count": 1, "labeled_count": 1})
        self.assertTrue(summary["last_seen_at"].endswith("Z"))
        # The detached row's alert had no server, so it counts in the totals but in no server.
        self.assertEqual(result["totals"], {"archived_count": 4, "unassigned_count": 1, "guilds": {
            str(self.guild): {"archived_count": 3, "unassigned_count": 0}}})
        await self.repository.register_alert(self.channel, "empty")
        empty = next(row for row in (await self.repository.review_alerts())["alerts"] if row["search_query"] == "empty")
        self.assertEqual((empty["archived_count"], empty["listing_count"], empty["last_seen_at"]), (0, 0, None))

    async def test_review_filters_include_disabled_discord_filters(self):
        await self.repository.add_filter(self.channel, "BABYMETAL", "text", "blacklist", "Tシャツ")
        await self.repository._call("test_disabled_filter", lambda: Filter.create(
            alert=self.alert["id"], method="legacy", type="whitelist", value="lost", enabled=False, matches=4))
        filters = await self.repository.review_filters(self.alert["id"])
        self.assertEqual([(row["method"], row["policy"], row["enabled"], row["matches"]) for row in filters],
                         [("text", "blacklist", True, 0), ("legacy", "whitelist", False, 4)])
        with self.assertRaises(ReviewNotFound):
            await self.repository.review_filters(999999)


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


class CandidateHistoryMigrationTests(unittest.TestCase):
    """Schema v3 archived a copy of every listing on every poll; v4 keeps one row per decision."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "v3.sqlite"
        configure_database(str(self.path))
        database.connect()
        database.create_tables(TABLES)
        # Rebuild the v3 shape: no last_seen_at, and the old (source, external_id) index.
        for statement in ('DROP INDEX "candidateobservation_last_seen_at"',
                          'DROP INDEX "candidateobservation_alert_id_source_external_id"',
                          'ALTER TABLE "candidate_observation" DROP COLUMN "last_seen_at"',
                          'CREATE INDEX "candidateobservation_source_external_id" '
                          'ON "candidate_observation" ("source", "external_id")'):
            database.execute_sql(statement)
        alert = Alert.create(channel_id=123, guild_id=456, search_query="poster")
        SchemaVersion.create(id=1, version=3)
        accepted, filtered = json.dumps(decision("accepted")), json.dumps(decision("filtered"))
        rows = [  # (external_id, decision, origin, minute)
            ("x", accepted, "live", 0), ("x", accepted, "live", 30), ("x", filtered, "live", 60),
            ("x", filtered, "live", 90), ("x", accepted, "live", 120),
            ("y", accepted, "live", 0), ("y", accepted, "live", 30), ("y", accepted, "live", 60),
            ("z", accepted, "item_import", 0), ("z", accepted, "item_import", 30),
            ("", filtered, "live", 0), ("", filtered, "live", 30),
        ]
        for external_id, recorded, origin, minute in rows:
            database.execute_sql(
                'INSERT INTO "candidate_observation" ("alert_id", "alert_snapshot_id", "channel_id", "search_query", '
                '"source", "external_id", "title", "normalized_title", "payload", "decision", "verdict", '
                '"observation_kind", "origin", "incomplete", "observed_at") '
                "VALUES (?, ?, 123, 'poster', 'mercari', ?, 'title', 'title', '{}', ?, ?, 'listing', ?, 0, ?)",
                (alert.id, alert.id, external_id, recorded, json.loads(recorded)["verdict"], origin,
                 str(datetime(2026, 10, 16, 7) + timedelta(minutes=minute))))
        # "x" has a label in each of its first two runs. "y" has two labels in one run; row 6
        # was labeled last, so its label wins over the later sighting's.
        database.execute_sql('INSERT INTO "candidate_feedback" ("candidate_id", "label", "updated_at") VALUES '
                             "(1, 'wrong_product', '2026-10-16 07:10:00'), (3, 'accessory', '2026-10-16 08:10:00'), "
                             "(6, 'unsure', '2026-10-16 09:00:00'), (7, 'relevant', '2026-10-16 08:00:00')")
        database.close()
        self.path.chmod(0o600)

    def tearDown(self):
        database.close()
        self.directory.cleanup()

    def table(self, connection):
        return connection.execute('SELECT "id", "external_id", "verdict", "observed_at", "last_seen_at" '
                                  'FROM "candidate_observation" ORDER BY "id"').fetchall()

    def test_upgrade_folds_repeated_sightings_moves_labels_keeps_imports_and_is_backed_up(self):
        with self.assertLogs("models", "WARNING") as logs:
            create_tables()
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], 4)
            self.assertEqual(self.table(connection), [
                (2, "x", "accepted", "2026-10-16 07:00:00", "2026-10-16 07:30:00"),
                (4, "x", "filtered", "2026-10-16 08:00:00", "2026-10-16 08:30:00"),
                (5, "x", "accepted", "2026-10-16 09:00:00", "2026-10-16 09:00:00"),
                (8, "y", "accepted", "2026-10-16 07:00:00", "2026-10-16 08:00:00"),
                (9, "z", "accepted", "2026-10-16 07:00:00", "2026-10-16 07:00:00"),
                (10, "z", "accepted", "2026-10-16 07:30:00", "2026-10-16 07:30:00"),
                (11, "", "filtered", "2026-10-16 07:00:00", "2026-10-16 07:00:00"),
                (12, "", "filtered", "2026-10-16 07:30:00", "2026-10-16 07:30:00"),
            ])
            # Each kept row has its run's newest label; the last "x" run has none and inherits one.
            self.assertEqual(connection.execute(
                "SELECT candidate_id, label, updated_at FROM candidate_feedback ORDER BY candidate_id").fetchall(), [
                (2, "wrong_product", "2026-10-16 07:10:00"),
                (4, "accessory", "2026-10-16 08:10:00"),
                (5, "accessory", "2026-10-16 08:10:00"),
                (8, "unsure", "2026-10-16 09:00:00"),
            ])
            column = next(row for row in connection.execute("PRAGMA table_info(candidate_observation)")
                          if row[1] == "last_seen_at")
            self.assertEqual(column[3], 1)
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(candidate_observation)")}
            self.assertIn("candidateobservation_alert_id_source_external_id", indexes)
            self.assertIn("candidateobservation_last_seen_at", indexes)
            self.assertNotIn("candidateobservation_source_external_id", indexes)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        backups = list(self.path.parent.glob(f"v3.sqlite.pre-v{SCHEMA_VERSION}.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(backups[0]) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidate_observation").fetchone()[0], 12)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidate_feedback").fetchone()[0], 4)
        migrated = next(record for record in logs.records if record.getMessage() == "database_migrated")
        self.assertEqual(migrated.fields["repeated_snapshots_removed"], 4)
        self.assertEqual(migrated.fields["labels_moved_to_latest"], 4)
        create_tables()
        self.assertEqual(list(self.path.parent.glob("*.bak")), backups)

    def test_failed_upgrade_rolls_back_to_the_v3_table(self):
        with patch("models._fold_repeated_snapshots", side_effect=RuntimeError("simulated fold failure")):
            with self.assertRaisesRegex(RuntimeError, "fold failure"):
                create_tables()
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0], 3)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(candidate_observation)")}
            self.assertNotIn("last_seen_at", columns)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidate_observation").fetchone()[0], 12)
