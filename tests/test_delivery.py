"""Real outbox persistence with a fake Discord REST adapter."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import hikari

from config import Settings
from delivery import DeliveryWorker
from domain import Listing, first_discord_id_at
from filtering import default_ruleset
from models import DeliveryJob, Item, Message, configure_database, create_tables, database, utcnow
from observability import Metrics
from repositories import Repository


def bulk_error(cause):
    """The error hikari raises when a bulk delete fails, with Discord's answer as its cause."""
    error = hikari.BulkDeleteError([])
    error.__cause__ = cause
    return error


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        configure_database(str(Path(self.directory.name) / "alerts.db"))
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(1111, "figure")
        self.alert = (await self.repository.list_alerts())[0]
        self.listing = Listing("auction-id", "yahooauction", "Japanese figure", 1, 5000,
                               url="https://example.com/item")
        self.rest = SimpleNamespace(create_message=AsyncMock(), add_reaction=AsyncMock(),
                                    create_dm_channel=AsyncMock(return_value=SimpleNamespace(id=9090)))
        self.rest.create_message.side_effect = [SimpleNamespace(id=value) for value in range(50001, 50010)]
        self.worker = DeliveryWorker(SimpleNamespace(rest=self.rest), self.repository, self.metrics, Settings())

    async def asyncTearDown(self):
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    async def rows(self, model):
        return await self.repository._call("test_inspect", lambda: list(model.select().order_by(model._meta.primary_key).dicts()))

    async def make_due(self, job_id):
        await self.repository._call("test_make_due", lambda: DeliveryJob.update(next_attempt_at=utcnow()).where(DeliveryJob.id == job_id).execute())

    async def test_reaction_failure_retries_existing_message_without_duplicate_post(self):
        await self.repository.observe(self.alert, self.listing)
        candidate = (await self.repository.due_deliveries())[0]
        self.rest.add_reaction.side_effect = [RuntimeError("temporary reaction failure"), None, None]
        await self.worker.deliver(candidate)
        job = (await self.rows(DeliveryJob))[0]
        self.assertEqual((job["status"], job["message_id"], job["attempts"]), ("pending", 50001, 1))
        self.assertEqual((await self.repository.lookup_message(1111, 50001))["external_id"], "auction-id")
        self.assertEqual(await self.repository.due_deliveries(), [])
        await self.make_due(candidate["id"])
        await self.worker.deliver(candidate)
        job = (await self.rows(DeliveryJob))[0]
        self.assertEqual((job["status"], job["message_id"], job["attempts"]), ("sent", 50001, 2))
        self.assertEqual(self.rest.create_message.await_count, 1)
        self.assertEqual(self.rest.add_reaction.await_count, 3)
        self.assertEqual(len(await self.rows(Message)), 1)

    async def test_failed_dm_does_not_block_channel_update_job(self):
        await self.repository.observe(self.alert, self.listing)
        item_id = (await self.rows(Item))[0]["id"]
        await self.repository.subscribe(item_id, 77)
        await self.repository.observe(self.alert, replace(self.listing, price=4000))
        jobs = await self.repository.due_deliveries()
        dm = next(job for job in jobs if job["kind"] == "dm")
        update = next(job for job in jobs if job["kind"] == "channel" and json.loads(job["payload"])["differences"])
        self.rest.create_dm_channel.side_effect = RuntimeError("temporary DM outage")
        await self.worker.deliver(dm)
        await self.worker.deliver(update)
        statuses = {row["id"]: row["status"] for row in await self.rows(DeliveryJob)}
        self.assertEqual((statuses[dm["id"]], statuses[update["id"]]), ("pending", "sent"))
        self.assertEqual(self.rest.create_message.await_args.args[0], 1111)
        self.assertEqual(self.metrics.registry.get_sample_value("auction_bot_delivery_attempts_total", {"kind": "dm", "outcome": "retry"}), 1)
        self.assertEqual(self.metrics.registry.get_sample_value("auction_bot_delivery_attempts_total", {"kind": "channel", "outcome": "sent"}), 1)

    async def test_historical_and_current_message_ids_keep_same_item_mapping(self):
        await self.repository.observe(self.alert, self.listing)
        await self.worker.deliver((await self.repository.due_deliveries())[0])
        await self.repository.observe(self.alert, replace(self.listing, price=4000))
        await self.worker.deliver((await self.repository.due_deliveries())[0])
        old = await self.repository.lookup_message(1111, 50001)
        current = await self.repository.lookup_message(1111, 50002)
        self.assertEqual(old["item_id"], current["item_id"])
        self.assertEqual((old["source"], old["external_id"]), ("yahooauction", "auction-id"))
        self.assertIsNone(await self.repository.lookup_message(2222, 50001))
        await self.repository.mark_message_deleted(1111, 50001)
        self.assertIsNone(await self.repository.lookup_message(1111, 50001))
        self.assertIsNotNone(await self.repository.lookup_message(1111, 50002))

    async def test_stale_candidate_after_unregister_makes_no_discord_request(self):
        await self.repository.observe(self.alert, self.listing)
        candidate = (await self.repository.due_deliveries())[0]
        await self.repository.unregister_alert(1111, "figure")
        await self.worker.deliver(candidate)
        self.rest.create_message.assert_not_awaited()
        self.rest.add_reaction.assert_not_awaited()
        self.assertEqual((await self.rows(DeliveryJob))[0]["status"], "cancelled")

    async def test_exhausted_delivery_attempts_leave_actionable_failed_job(self):
        await self.repository.observe(self.alert, self.listing)
        candidate = (await self.repository.due_deliveries())[0]
        self.worker.settings = replace(Settings(), delivery_attempts=2)
        self.rest.create_message.side_effect = RuntimeError("temporary Discord outage")
        await self.worker.deliver(candidate)
        await self.make_due(candidate["id"])
        await self.worker.deliver(candidate)
        job = (await self.rows(DeliveryJob))[0]
        self.assertEqual((job["status"], job["attempts"], job["last_error"]), ("failed", 2, "RuntimeError"))
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual((await self.repository.stats())["failed"], 1)

    async def test_cancelled_delivery_joins_acknowledgment_before_exiting(self):
        await self.repository.observe(self.alert, self.listing)
        candidate = (await self.repository.due_deliveries())[0]
        started, release = asyncio.Event(), asyncio.Event()
        acknowledge = self.repository.acknowledge_delivery

        async def blocked_acknowledgment(*args):
            started.set()
            await release.wait()
            await acknowledge(*args)

        with patch.object(self.repository, "acknowledge_delivery", new=AsyncMock(side_effect=blocked_acknowledgment)) as fake_ack:
            delivery = asyncio.create_task(self.worker.deliver(candidate))
            try:
                await asyncio.wait_for(started.wait(), 1)
                self.assertEqual(self.rest.create_message.await_count, 1)
                delivery.cancel()
                await asyncio.sleep(0)
                self.assertFalse(delivery.done(), "shutdown must wait for durable message acknowledgment")
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(delivery, 1)
            finally:
                release.set()
                await asyncio.gather(delivery, return_exceptions=True)
            fake_ack.assert_awaited_once_with(candidate["id"], 50001)

        job = (await self.rows(DeliveryJob))[0]
        self.assertEqual((job["status"], job["message_id"]), ("pending", 50001))
        self.assertIsNotNone(await self.repository.lookup_message(1111, 50001))
        self.rest.add_reaction.assert_not_awaited()
        await self.worker.deliver(candidate)
        self.assertEqual((await self.rows(DeliveryJob))[0]["status"], "sent")
        self.assertEqual(self.rest.create_message.await_count, 1)

    async def post(self, *external_ids, ages=None):
        """Post one listing per ID and return the message IDs. The fake Discord numbers messages
        from 50001, which dates them to 2015; `ages` gives each post an ID from that long ago instead."""
        ids = None
        if ages is not None:
            now = datetime.now(timezone.utc)
            ids = [first_discord_id_at(now - age) + index for index, age in enumerate(ages)]
            self.rest.create_message.side_effect = [SimpleNamespace(id=message_id) for message_id in ids]
        for external_id in external_ids:
            await self.repository.observe(self.alert, replace(self.listing, id=external_id))
        for job in await self.repository.due_deliveries():
            await self.worker.deliver(job)
        return ids or [row["message_id"] for row in await self.rows(Message)]

    async def queue_removals(self, *message_ids):
        version = await self.repository.publish_review_rules(self.alert["id"], default_ruleset(), None)
        return await self.repository.queue_post_removals(self.alert["id"], int(version["id"]), list(message_ids))

    async def removals(self):
        return {row["message_id"]: row["status"] for row in await self.rows(DeliveryJob) if row["kind"] == "delete"}

    async def test_post_removal_waits_for_alerts_then_deletes_the_post(self):
        await self.post("first")
        self.rest.delete_message = AsyncMock()
        self.assertEqual(await self.queue_removals(50001), 1)
        await self.repository.observe(self.alert, replace(self.listing, id="second"))
        waiting = await self.repository.due_deliveries()
        self.assertEqual([job["kind"] for job in waiting], ["channel"])
        # The outbox gauges, and the backlog alerts on them, only count posts and DMs.
        self.assertEqual((await self.repository.stats())["pending"], 1)
        await self.worker.deliver(waiting[0])
        removal = (await self.repository.due_deliveries())[0]
        self.assertEqual((removal["kind"], removal["message_id"]), ("delete", 50001))
        await self.worker.deliver(removal)
        self.rest.delete_message.assert_awaited_once_with(1111, 50001)
        self.assertIsNone(await self.repository.lookup_message(1111, 50001))
        self.assertIsNotNone(await self.repository.lookup_message(1111, 50002))
        self.assertEqual(await self.removals(), {50001: "sent"})
        self.assertEqual(self.metrics.registry.get_sample_value(
            "auction_bot_delivery_attempts_total", {"kind": "delete", "outcome": "sent"}), 1)

    async def test_post_removal_counts_a_missing_post_as_removed_and_stops_on_forbidden(self):
        await self.post("first", "second")
        self.assertEqual(await self.queue_removals(50001, 50002), 2)

        async def delete(channel_id, message_id):
            if message_id == 50001:
                raise hikari.NotFoundError("https://discord.test", {}, "", message="Unknown Message", code=10008)
            raise hikari.ForbiddenError("https://discord.test", {}, "", message="Missing permissions", code=50013)

        self.rest.delete_message = AsyncMock(side_effect=delete)
        for job in await self.repository.due_deliveries():
            await self.worker.deliver(job)
        self.assertEqual(await self.removals(), {50001: "sent", 50002: "failed"})
        self.assertIsNone(await self.repository.lookup_message(1111, 50001))
        self.assertIsNotNone(await self.repository.lookup_message(1111, 50002))
        self.assertEqual((await self.repository.stats())["failed"], 0)
        run = (await self.repository.post_removal_status(self.alert["id"]))["run"]
        self.assertEqual((run["total"], run["removed"], run["failed"], run["pending"]), (2, 1, 1, 0))

    async def test_post_removal_skips_posts_that_went_or_got_a_subscriber(self):
        await self.post("first", "second")
        self.assertEqual(await self.queue_removals(50001, 50002), 2)
        await self.repository.mark_message_deleted(1111, 50001)
        await self.repository.subscribe((await self.repository.lookup_message(1111, 50002))["item_id"], 77)
        self.rest.delete_message = AsyncMock()
        for job in await self.repository.due_deliveries():
            await self.worker.deliver(job)
        self.rest.delete_message.assert_not_awaited()
        self.assertEqual(await self.removals(), {50001: "cancelled", 50002: "cancelled"})

    async def remove_due(self):
        await self.worker.remove_due(await self.repository.due_deliveries())

    async def test_recent_posts_go_in_one_bulk_request_and_older_ones_one_at_a_time(self):
        ids = await self.post("new", "newer", "old", ages=[timedelta(hours=3), timedelta(hours=1), timedelta(days=20)])
        self.rest.delete_messages, self.rest.delete_message = AsyncMock(), AsyncMock()
        self.assertEqual(await self.queue_removals(*ids), 3)
        await self.remove_due()
        self.rest.delete_messages.assert_awaited_once_with(1111, [ids[1], ids[0]])
        self.rest.delete_message.assert_awaited_once_with(1111, ids[2])
        self.assertEqual(set((await self.removals()).values()), {"sent"})
        for message_id in ids:
            self.assertIsNone(await self.repository.lookup_message(1111, message_id))
        self.assertEqual(self.metrics.registry.get_sample_value(
            "auction_bot_delivery_attempts_total", {"kind": "delete", "outcome": "sent"}), 3)

    async def test_bulk_delete_names_each_post_once(self):
        ids = await self.post("first", "second", ages=[timedelta(hours=2), timedelta(hours=1)])
        self.rest.delete_messages = AsyncMock()
        await self.queue_removals(*ids)
        # A failed removal put back with outbox-retry can wait next to a newer one for the same post.
        item = (await self.repository.lookup_message(1111, ids[0]))["item_id"]
        await self.repository._call("test_repeat", lambda: DeliveryJob.create(
            item=item, alert=self.alert["id"], kind="delete", destination_id=1111, message_id=ids[0], payload="{}"))
        await self.remove_due()
        self.rest.delete_messages.assert_awaited_once_with(1111, [ids[1], ids[0]])
        self.assertEqual([job["status"] for job in await self.rows(DeliveryJob) if job["kind"] == "delete"], ["sent"] * 3)

    async def test_a_lone_recent_post_is_deleted_without_bulk(self):
        ids = await self.post("only", ages=[timedelta(hours=1)])
        self.rest.delete_messages, self.rest.delete_message = AsyncMock(), AsyncMock()
        await self.queue_removals(*ids)
        await self.remove_due()
        self.rest.delete_messages.assert_not_awaited()
        self.rest.delete_message.assert_awaited_once_with(1111, ids[0])

    async def test_refused_bulk_delete_falls_back_to_one_post_at_a_time(self):
        ids = await self.post("first", "second", ages=[timedelta(hours=2), timedelta(hours=1)])
        forbidden = hikari.ForbiddenError("https://discord.test", {}, "", message="Missing Permissions", code=50013)
        self.rest.delete_messages = AsyncMock(side_effect=bulk_error(forbidden))
        self.rest.delete_message = AsyncMock()
        await self.queue_removals(*ids)
        await self.remove_due()
        self.rest.delete_message.assert_not_awaited()
        removals = [job for job in await self.rows(DeliveryJob) if job["kind"] == "delete"]
        self.assertEqual({(job["status"], job["attempts"], job["last_error"]) for job in removals},
                         {("pending", 1, "ForbiddenError")})
        # Due again at once; this channel is not tried in bulk again for a while.
        await self.remove_due()
        self.rest.delete_messages.assert_awaited_once()
        self.assertEqual(self.rest.delete_message.await_count, 2)
        self.assertEqual(set((await self.removals()).values()), {"sent"})

    async def test_failed_bulk_delete_is_retried_later(self):
        ids = await self.post("first", "second", ages=[timedelta(hours=2), timedelta(hours=1)])
        self.rest.delete_messages = AsyncMock(side_effect=bulk_error(RuntimeError("Discord outage")))
        await self.queue_removals(*ids)
        await self.remove_due()
        removals = [job for job in await self.rows(DeliveryJob) if job["kind"] == "delete"]
        self.assertEqual({(job["status"], job["last_error"]) for job in removals}, {("pending", "RuntimeError")})
        self.assertEqual(await self.repository.due_deliveries(), [])
        self.assertEqual(self.metrics.registry.get_sample_value(
            "auction_bot_delivery_attempts_total", {"kind": "delete", "outcome": "retry"}), 2)

    async def test_older_posts_go_a_few_per_round(self):
        ids = await self.post(*(f"listing-{index}" for index in range(7)))
        self.rest.delete_message = AsyncMock()
        self.assertEqual(await self.queue_removals(*ids), 7)
        await self.remove_due()
        self.assertEqual(self.rest.delete_message.await_count, 5)
        self.assertEqual(sorted((await self.removals()).values()), ["pending"] * 2 + ["sent"] * 5)


if __name__ == "__main__":
    unittest.main()
