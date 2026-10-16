"""All database work runs on one dedicated thread; observations and outbox writes are atomic."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import timedelta
import json
import logging
import time

from peewee import chunked, fn

from domain import FilterRule, changes
from models import (Alert, AlertItem, Blacklist, DeliveryJob, Filter, Item, Message,
                    Notification, database, utcnow)
from review_repository import ReviewRepositoryMixin


logger = logging.getLogger(__name__)


class Repository(ReviewRepositoryMixin):
    def __init__(self, metrics):
        self.metrics = metrics
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auction-db")
        self.closed = False

    def _invoke(self, function, args):
        database.connect(reuse_if_open=True)
        return function(*args)

    async def _call(self, operation, function, *args):
        if self.closed:
            raise RuntimeError("Repository is closed")
        started = time.monotonic()
        context = copy_context()
        try:
            return await asyncio.get_running_loop().run_in_executor(
                self.executor, context.run, self._invoke, function, args)
        except Exception:
            self.metrics.db_errors.labels(operation=operation).inc()
            raise
        finally:
            self.metrics.db_duration.labels(operation=operation).observe(time.monotonic() - started)

    async def start(self):
        await self._call("connect", lambda: database.execute_sql("SELECT 1").fetchone())

    async def close(self):
        if not self.closed:
            await asyncio.get_running_loop().run_in_executor(self.executor, database.close)
            self.closed = True
            await asyncio.to_thread(self.executor.shutdown, wait=True)

    async def list_alerts(self, channel_id=None, guild_id=None):
        def select():
            query = Alert.select().order_by(Alert.channel_id, Alert.id)
            if guild_id is not None:
                scope = Alert.guild_id == guild_id
                if channel_id is not None:
                    scope |= Alert.channel_id == channel_id
                query = query.where(scope)
            elif channel_id is not None:
                query = query.where(Alert.channel_id == channel_id)
            return list(query.dicts())
        return await self._call("list_alerts", select)

    async def register_alert(self, channel_id, search_query, guild_id=None):
        search_query = search_query.strip()
        if not search_query or len(search_query) > 256:
            raise ValueError("Search queries must contain 1 to 256 characters")
        def create():
            with database.atomic():
                alert, created = Alert.get_or_create(channel_id=channel_id, search_query=search_query,
                                                     defaults={"guild_id": guild_id})
                if alert.guild_id is None and guild_id is not None:
                    Alert.update(guild_id=guild_id).where(Alert.id == alert.id).execute()
                return created
        return await self._call("register_alert", create)

    async def reconcile_guilds(self, channel_to_guild):
        """Set the server of alerts that have none, from a channel ID to server ID mapping.

        Alerts that already have a server keep it. Returns how many alerts got one.
        """
        by_guild = {}
        for channel_id, guild_id in channel_to_guild.items():
            by_guild.setdefault(int(guild_id), []).append(int(channel_id))

        def update():
            updated = 0
            with database.atomic():
                for guild_id, channel_ids in by_guild.items():
                    for batch in chunked(channel_ids, 500):
                        updated += Alert.update(guild_id=guild_id).where(
                            Alert.channel_id.in_(batch), Alert.guild_id.is_null()).execute()
            return updated
        if not by_guild:
            return 0
        updated = await self._call("reconcile_guilds", update)
        if updated:
            logger.info("alert_guilds_reconciled", extra={"fields": {
                "guild_ids": sorted(by_guild), "alerts": updated}})
        return updated

    async def unregister_alert(self, channel_id, search_query):
        def delete():
            with database.atomic():
                alert = Alert.get_or_none(Alert.channel_id == channel_id, Alert.search_query == search_query)
                if alert is None:
                    return False
                DeliveryJob.update(status="cancelled").where(
                    DeliveryJob.alert == alert, DeliveryJob.status.in_(("pending", "failed"))).execute()
                alert.delete_instance()
                return True
        return await self._call("unregister_alert", delete)

    async def list_filters(self, channel_id, search_query=None):
        def select():
            query = (Filter.select(Filter, Alert.search_query).join(Alert)
                     .where(Alert.channel_id == channel_id).order_by(Filter.id))
            if search_query is not None:
                query = query.where(Alert.search_query == search_query)
            rows = list(query.dicts())
            for row in rows:
                row["alert_id"] = row.pop("alert")
            return rows
        return await self._call("list_filters", select)

    async def add_filter(self, channel_id, search_query, method, policy, value):
        if not value or len(value) > (256 if method == "regex" else 1024):
            raise ValueError("Filter value is empty or too long")
        FilterRule(0, method, policy, value).matcher()
        def create():
            alert = Alert.get_or_none(Alert.channel_id == channel_id, Alert.search_query == search_query)
            if alert is None:
                return None
            if Filter.select().where(Filter.alert == alert).count() >= 50:
                raise ValueError("An alert may have at most 50 filters")
            return Filter.create(alert=alert, method=method, type=policy, value=value).id
        return await self._call("add_filter", create)

    async def delete_filter(self, channel_id, filter_id):
        def delete():
            alerts = Alert.select(Alert.id).where(Alert.channel_id == channel_id)
            return bool(Filter.delete().where(Filter.id == filter_id, Filter.alert.in_(alerts)).execute())
        return await self._call("delete_filter", delete)

    async def filters_for_alert(self, alert_id):
        def select():
            return [FilterRule(row.id, row.method, row.type, row.value) for row in
                    Filter.select().where(Filter.alert == alert_id, Filter.enabled)]
        return await self._call("filters_for_alert", select)

    async def record_filter_matches(self, counts):
        if not counts:
            return
        def update():
            with database.atomic():
                for filter_id, count in counts.items():
                    Filter.update(matches=Filter.matches + count).where(Filter.id == filter_id).execute()
        await self._call("record_filter_matches", update)

    async def is_blacklisted(self, source, external_id, channel_id):
        def select():
            return (Blacklist.select().join(Item)
                    .where(Item.checker == source, Item.item_id == external_id,
                           Blacklist.channel_id == channel_id).exists())
        return await self._call("is_blacklisted", select)

    def _enqueue(self, item, alert, kind, destination_id, listing, differences):
        payload = {"listing": listing.payload(), "differences": differences,
                   "search_query": alert.search_query}
        DeliveryJob.create(item=item, alert=alert, kind=kind,
                           destination_id=destination_id, payload=json.dumps(payload, ensure_ascii=False))

    async def observe(self, alert_data, listing, threshold=500, *, decision_payload=None,
                      ruleset_version_id=None):
        def persist():
            with database.atomic():
                if decision_payload is not None:
                    self._archive_candidate_sync(alert_data, listing.payload(), decision_payload,
                                                 ruleset_version_id)
                alert = Alert.get_or_none(Alert.id == alert_data["id"],
                                          Alert.channel_id == alert_data["channel_id"],
                                          Alert.search_query == alert_data["search_query"])
                if alert is None:
                    return "unregistered"
                item = Item.get_or_none(Item.checker == listing.source, Item.item_id == listing.id)
                if item and Blacklist.select().where(
                        Blacklist.item == item, Blacklist.channel_id == alert.channel_id).exists():
                    return "blacklisted"
                now = utcnow()
                values = {"title": listing.title, "stock": listing.stock, "price": listing.price,
                          "buyout_price": listing.buyout_price, "image_url": listing.image_url,
                          "url": listing.url, "end_time": listing.end_time}
                global_differences = changes(item, listing, threshold) if item else []
                if item is None:
                    item = Item.create(item_id=listing.id, checker=listing.source, **values)
                else:
                    modified = {key: value for key, value in values.items() if getattr(item, key) != value}
                    if modified:
                        modified["updated_at"] = now
                    Item.update(last_seen_at=now, **modified).where(Item.id == item.id).execute()
                previous = AlertItem.get_or_none(AlertItem.alert == alert, AlertItem.item == item)
                differences = changes(previous, listing, threshold) if previous else []
                baseline = {"stock": listing.stock, "price": listing.price,
                            "buyout_price": listing.buyout_price, "observed_at": now}
                if previous is None:
                    AlertItem.create(alert=alert, item=item, **baseline)
                else:
                    AlertItem.update(**baseline).where(AlertItem.id == previous.id).execute()
                if not item.muted:
                    if previous is None or differences:
                        self._enqueue(item, alert, "channel", alert.channel_id, listing, differences)
                    # Listing-wide subscriptions receive a global change once even when multiple alerts match.
                    if global_differences:
                        for subscriber in Notification.select().where(Notification.item == item):
                            self._enqueue(item, alert, "dm", subscriber.user_id, listing, global_differences)
                if item.muted:
                    return "muted"
                return "new" if previous is None else "changed" if differences else "unchanged"
        return await self._call("observe", persist)

    async def lookup_message(self, channel_id, message_id):
        def select():
            row = (Message.select(Message, Item).join(Item).where(
                Message.message_id == message_id, Message.channel_id == channel_id,
                ~Message.deleted).get_or_none())
            if row is None:
                return None
            return {"item_id": row.item_id, "external_id": row.item.item_id,
                    "source": row.item.checker, "channel_id": row.channel_id, "message_id": row.message_id}
        return await self._call("lookup_message", select)

    async def mark_message_deleted(self, channel_id, message_id):
        await self._call("delete_message", lambda: Message.update(deleted=True).where(
            Message.channel_id == channel_id, Message.message_id == message_id).execute())

    async def blacklist_item(self, item_id, channel_id):
        def create():
            with database.atomic():
                Blacklist.insert(item=item_id, channel_id=channel_id).on_conflict_ignore().execute()
                DeliveryJob.update(status="cancelled").where(
                    DeliveryJob.item == item_id, DeliveryJob.kind == "channel",
                    DeliveryJob.destination_id == channel_id, DeliveryJob.status.in_(("pending", "failed"))).execute()
        await self._call("blacklist_item", create)

    async def subscribe(self, item_id, user_id):
        def create():
            _, created = Notification.get_or_create(item=item_id, user_id=int(user_id))
            return created
        return await self._call("subscribe", create)

    async def unsubscribe(self, item_id, user_id):
        def delete():
            with database.atomic():
                count = Notification.delete().where(Notification.item == item_id, Notification.user_id == user_id).execute()
                DeliveryJob.update(status="cancelled").where(
                    DeliveryJob.item == item_id, DeliveryJob.kind == "dm",
                    DeliveryJob.destination_id == user_id, DeliveryJob.status.in_(("pending", "failed"))).execute()
                return bool(count)
        return await self._call("unsubscribe", delete)

    async def due_deliveries(self, limit=50, removal_limit=100):
        """Posts and DMs first. Post removals from Filter Lab come only when nothing else waits,
        newest post first, so the ones young enough for Discord's bulk delete come together."""
        def select():
            due = DeliveryJob.select().where(DeliveryJob.status == "pending", DeliveryJob.next_attempt_at <= utcnow())
            jobs = list(due.where(DeliveryJob.kind != "delete").order_by(DeliveryJob.created_at, DeliveryJob.id)
                        .limit(limit).dicts())
            return jobs or list(due.where(DeliveryJob.kind == "delete").order_by(DeliveryJob.message_id.desc())
                                .limit(removal_limit).dicts())
        return await self._call("due_deliveries", select)

    async def begin_delivery(self, job_id):
        def begin():
            with database.atomic():
                job = DeliveryJob.get_or_none(DeliveryJob.id == job_id, DeliveryJob.status == "pending",
                                              DeliveryJob.next_attempt_at <= utcnow())
                if job is None:
                    return None
                if job.kind == "delete":
                    # Skip posts that are already gone, and keep posts someone subscribed to meanwhile.
                    allowed = (Message.select().where(Message.message_id == job.message_id, ~Message.deleted).exists()
                               and not Notification.select().where(Notification.item == job.item_id).exists())
                else:
                    allowed = (not Blacklist.select().where(Blacklist.item == job.item_id,
                               Blacklist.channel_id == job.destination_id).exists()) if job.kind == "channel" else (
                               Notification.select().where(Notification.item == job.item_id,
                               Notification.user_id == job.destination_id).exists())
                if not allowed:
                    job.status = "cancelled"
                    job.save(only=[DeliveryJob.status])
                    return None
                job.attempts += 1
                job.save(only=[DeliveryJob.attempts])
                return dict(job.__data__)
        return await self._call("begin_delivery", begin)

    async def acknowledge_delivery(self, job_id, message_id):
        def acknowledge():
            with database.atomic():
                job = DeliveryJob.get_by_id(job_id)
                DeliveryJob.update(message_id=message_id).where(DeliveryJob.id == job_id).execute()
                if job.kind == "channel":
                    Message.insert(message_id=message_id, item=job.item_id, alert=job.alert_id,
                                   channel_id=job.destination_id).on_conflict_ignore().execute()
        await self._call("acknowledge_delivery", acknowledge)

    async def complete_removals(self, jobs):
        """Mark the posts of finished removal jobs deleted and the jobs done, in one transaction."""
        def complete():
            with database.atomic():
                for job in jobs:
                    Message.update(deleted=True).where(Message.channel_id == job["destination_id"],
                                                       Message.message_id == job["message_id"]).execute()
                DeliveryJob.update(status="sent", completed_at=utcnow(), last_error=None).where(
                    DeliveryJob.id.in_([job["id"] for job in jobs]), DeliveryJob.status == "pending").execute()
        await self._call("complete_removals", complete)

    async def complete_delivery(self, job_id):
        await self._call("complete_delivery", lambda: DeliveryJob.update(status="sent", completed_at=utcnow(), last_error=None)
                        .where(DeliveryJob.id == job_id, DeliveryJob.status == "pending").execute())

    async def fail_delivery(self, job_id, error_type, delay, permanent=False):
        await self._call("fail_delivery", lambda: DeliveryJob.update(
            status="failed" if permanent else "pending", last_error=error_type,
            next_attempt_at=utcnow() + timedelta(seconds=delay)).where(
            DeliveryJob.id == job_id, DeliveryJob.status == "pending").execute())

    async def stats(self):
        def select():
            # Post removals are left out: a long cleanup is expected to take a while, and the
            # backlog alerts are about posts and DMs that are late. Filter Lab shows its progress.
            jobs = DeliveryJob.select().where(DeliveryJob.kind != "delete")
            pending = jobs.where(DeliveryJob.status == "pending")
            oldest = pending.select(fn.MIN(DeliveryJob.created_at)).scalar()
            # MIN bypasses DateTimeField conversion on some Peewee versions.
            if oldest and isinstance(oldest, str):
                from datetime import datetime
                oldest = datetime.fromisoformat(oldest)
            alert_metadata = list(Alert.select(Alert.id, Alert.channel_id, Alert.search_query).dicts())
            return {"alerts": len(alert_metadata), "alert_metadata": alert_metadata, "pending": pending.count(),
                    "failed": jobs.where(DeliveryJob.status == "failed").count(),
                    "oldest_pending_age": max(0, (utcnow() - oldest).total_seconds()) if oldest else 0,
                    "disabled_legacy_filters": Filter.select().where(~Filter.enabled).count()}
        return await self._call("stats", select)
