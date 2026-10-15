"""Real outbox persistence with a fake Discord REST adapter."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from config import Settings
from delivery import DeliveryWorker
from domain import Listing
from models import DeliveryJob, Item, Message, configure_database, create_tables, database, utcnow
from observability import Metrics
from repositories import Repository


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


if __name__ == "__main__":
    unittest.main()
