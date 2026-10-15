"""Discord is an outbound adapter; each durable channel/DM job retries independently."""
import asyncio
from datetime import datetime
import json
import logging
import time

import hikari
from peewee import OperationalError

from observability import log_context

logger = logging.getLogger(__name__)
COLORS = {"yahooauction": 0xFFA500, "mercari": 0xFF0000, "surugaya": 0x0000FF}


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

    async def deliver(self, candidate):
        job = await self.repository.begin_delivery(candidate["id"])
        if job is None:
            return
        token = log_context.set({**log_context.get(), "delivery_id": job["id"], "kind": job["kind"]})
        started = time.monotonic()
        outcome = "sent"
        try:
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
            permanent = isinstance(error, (hikari.ForbiddenError, hikari.NotFoundError,
                                           hikari.BadRequestError, ValueError, KeyError, TypeError))
            permanent = permanent or job["attempts"] >= self.settings.delivery_attempts
            outcome = "failed" if permanent else "retry"
            await self.repository.fail_delivery(job["id"], type(error).__name__,
                                                min(300, 5 * 2 ** min(job["attempts"] - 1, 6)), permanent)
            logger.exception("delivery_failed", extra={"fields": {"attempt": job["attempts"], "retry": not permanent}})
        finally:
            self.metrics.deliveries.labels(kind=job["kind"], outcome=outcome).inc()
            self.metrics.delivery_duration.labels(kind=job["kind"]).observe(time.monotonic() - started)
            log_context.reset(token)

    async def run(self):
        while True:
            try:
                jobs = await self.repository.due_deliveries()
                for job in jobs:
                    await self.deliver(job)
            except OperationalError:
                logger.exception("delivery_repository_unavailable")
                await asyncio.sleep(5)
                continue
            if not jobs:
                await asyncio.sleep(1)
