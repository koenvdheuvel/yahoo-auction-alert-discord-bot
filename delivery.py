"""Discord is an outbound adapter; each durable channel/DM job retries independently."""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
import time

import hikari
from peewee import OperationalError

from domain import first_discord_id_at
from observability import log_context

logger = logging.getLogger(__name__)
COLORS = {"yahooauction": 0xFFA500, "mercari": 0xFF0000, "surugaya": 0x0000FF}
PERMANENT_ERRORS = (hikari.ForbiddenError, hikari.NotFoundError, hikari.BadRequestError, ValueError, KeyError, TypeError)
# Discord's bulk delete takes 2 to 100 messages younger than 14 days and needs the Manage
# Messages permission. The hour of margin covers clock differences and time in the queue.
BULK_DELETE_SIZE = 100
BULK_DELETE_AGE = timedelta(days=14) - timedelta(hours=1)
# After Discord refuses a bulk delete in a channel, its posts go one at a time for this long.
BULK_REFUSED_SECONDS = 3600
# Posts deleted one request each per round, so new alert posts never wait long behind them.
SINGLE_REMOVALS_PER_ROUND = 5


def create_embed(payload):
    item, differences = payload["listing"], payload["differences"]
    embed = hikari.Embed(title=item["title"][:256], url=item["url"] or None,
                         color=0x00FF00 if differences else COLORS.get(item["source"], 0x808080))
    if item["image_url"]:
        embed.set_image(item["image_url"])
    embed.add_field("Price", f'¥{item["price"]}', inline=True)
    if item["buyout_price"] > 0:
        embed.add_field("Buyout Price", f'¥{item["buyout_price"]}', inline=True)
    if item["stock"] > 1:
        embed.add_field("Stock", str(item["stock"]), inline=True)
    if item.get("end_time"):
        end_time = datetime.fromisoformat(item["end_time"])
        embed.add_field("End Time", f"<t:{round(end_time.timestamp())}:R>")
    for difference in differences:
        embed.add_field("Update", difference, inline=False)
    embed.set_footer(f'Source: {item["source"]} — #{item["id"]} - {payload["search_query"]}'[:2048])
    return embed


class DeliveryWorker:
    def __init__(self, bot, repository, metrics, settings):
        self.bot, self.repository, self.metrics, self.settings = bot, repository, metrics, settings
        # Channel ID to the monotonic time until which bulk deletes are not tried there.
        self.bulk_refused = {}

    async def deliver(self, candidate):
        job = await self.repository.begin_delivery(candidate["id"])
        if job is not None:
            await self.send(job)

    async def send(self, job):
        """One attempt at a job that begin_delivery handed out."""
        token = log_context.set({**log_context.get(), "delivery_id": job["id"], "kind": job["kind"]})
        started = time.monotonic()
        outcome = "sent"
        try:
            if job["kind"] == "delete":
                await self.remove(job)
                return
            embed = create_embed(json.loads(job["payload"]))
            destination = job["destination_id"]
            if job["kind"] == "dm":
                destination = (await self.bot.rest.create_dm_channel(destination)).id
            message_id = job["message_id"]
            if message_id is None:
                message = await self.bot.rest.create_message(destination, embed=embed)
                message_id = int(message.id)
                # Retain the acknowledged message before reactions; retries reuse it.
                acknowledgment = asyncio.create_task(
                    self.repository.acknowledge_delivery(job["id"], message_id))
                try:
                    await asyncio.shield(acknowledgment)
                except asyncio.CancelledError:
                    # Join the shielded work before the runtime closes the database thread.
                    try:
                        await acknowledgment
                    except Exception:
                        logger.exception("delivery_acknowledgment_failed_during_shutdown")
                    raise
            if job["kind"] == "channel":
                await self.bot.rest.add_reaction(destination, message_id, "🗑️")
                await self.bot.rest.add_reaction(destination, message_id, "🔔")
            await self.repository.complete_delivery(job["id"])
            logger.info("delivery_sent")
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as error:
            outcome = await self.fail(job, error)
            logger.exception("delivery_failed", extra={"fields": {"attempt": job["attempts"], "retry": outcome == "retry"}})
        finally:
            self.record(job, outcome, started)
            log_context.reset(token)

    def record(self, job, outcome, started):
        self.metrics.deliveries.labels(kind=job["kind"], outcome=outcome).inc()
        self.metrics.delivery_duration.labels(kind=job["kind"]).observe(time.monotonic() - started)

    async def fail(self, job, error):
        """Save a failed attempt, to retry after a growing delay or to give up on. Returns the outcome."""
        permanent = isinstance(error, PERMANENT_ERRORS) or job["attempts"] >= self.settings.delivery_attempts
        await self.repository.fail_delivery(job["id"], type(error).__name__,
                                            min(300, 5 * 2 ** min(job["attempts"] - 1, 6)), permanent)
        return "failed" if permanent else "retry"

    async def remove(self, job):
        """Delete one post that the dashboard queued because the published rules filter its listing."""
        try:
            await self.bot.rest.delete_message(job["destination_id"], job["message_id"])
        except hikari.NotFoundError:
            pass  # Already deleted, by hand or with the 🗑️ reaction.
        await self.repository.complete_removals([job])
        logger.info("post_removed", extra={"fields": {"message_id": job["message_id"]}})

    async def remove_due(self, jobs):
        """Delete queued posts. Posts under 14 days old go in bulk, up to 100 per channel and request;
        older posts, and posts in channels that refused a bulk delete, go one request each, a few per round."""
        recent_since = first_discord_id_at(datetime.now(timezone.utc) - BULK_DELETE_AGE)
        now = time.monotonic()
        recent, single = defaultdict(list), []
        for job in jobs:
            if job["message_id"] >= recent_since and self.bulk_refused.get(job["destination_id"], 0) <= now:
                recent[job["destination_id"]].append(job)
            else:
                single.append(job)
        for channel_id, group in recent.items():
            for start in range(0, len(group), BULK_DELETE_SIZE):
                await self.remove_bulk(channel_id, group[start:start + BULK_DELETE_SIZE])
        for job in single[:SINGLE_REMOVALS_PER_ROUND]:
            await self.deliver(job)

    async def remove_bulk(self, channel_id, candidates):
        """Delete up to 100 recent posts of one channel with Discord's bulk delete."""
        jobs = [job for job in [await self.repository.begin_delivery(candidate["id"]) for candidate in candidates] if job]
        # Discord refuses a batch that repeats an ID, or that has fewer than two.
        message_ids = list(dict.fromkeys(job["message_id"] for job in jobs))
        if len(message_ids) < 2:
            for job in jobs:
                await self.send(job)
            return
        token = log_context.set({**log_context.get(), "kind": "delete", "channel_id": channel_id})
        started = time.monotonic()
        try:
            error = None
            try:
                await self.bot.rest.delete_messages(channel_id, message_ids)
            except hikari.BulkDeleteError as bulk_error:
                # hikari wraps Discord's answer; the batch is one request, so nothing was deleted.
                error = bulk_error.__cause__ or bulk_error
            except Exception as other:
                error = other
            if error is None or isinstance(error, hikari.NotFoundError):
                # Discord ignores IDs of posts that are already gone; an unknown channel took its posts with it.
                await self.repository.complete_removals(jobs)
                outcomes = ["sent"] * len(jobs)
                logger.info("posts_removed", extra={"fields": {"count": len(jobs)}})
            elif isinstance(error, (hikari.ForbiddenError, hikari.BadRequestError)):
                # Most likely no Manage Messages permission in the channel. The posts are due again
                # at once and go one at a time from the next round.
                self.bulk_refused[channel_id] = time.monotonic() + BULK_REFUSED_SECONDS
                for job in jobs:
                    await self.repository.fail_delivery(job["id"], type(error).__name__, 0, False)
                outcomes = ["retry"] * len(jobs)
                logger.warning("bulk_delete_refused", extra={"fields": {"error": type(error).__name__,
                                                                          "count": len(jobs)}})
            else:
                outcomes = [await self.fail(job, error) for job in jobs]
                logger.warning("bulk_delete_failed", exc_info=error, extra={"fields": {"count": len(jobs)}})
            for job, outcome in zip(jobs, outcomes):
                self.record(job, outcome, started)
        finally:
            log_context.reset(token)

    async def run(self):
        while True:
            try:
                jobs = await self.repository.due_deliveries()
                # Removals only come when no post or DM is due.
                if jobs and jobs[0]["kind"] == "delete":
                    await self.remove_due(jobs)
                else:
                    for job in jobs:
                        await self.deliver(job)
            except OperationalError:
                logger.exception("delivery_repository_unavailable")
                await asyncio.sleep(5)
                continue
            if not jobs:
                await asyncio.sleep(1)
