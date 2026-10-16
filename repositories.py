"""All database work runs on one dedicated thread; observations and outbox writes are atomic."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import timedelta, timezone
import json
import logging
import time

from peewee import JOIN, chunked, fn

from domain import FilterRule, changes
from models import (Alert, AlertItem, Blacklist, DeliveryJob, Filter, Item, Message,
                    Notification, database, utcnow)
from review_repository import (POST_REMOVAL_SCAN_LIMIT, ReviewRepositoryMixin, live_posts,
                               post_json, queue_removals, queued_removals, removal_days, removal_run)


logger = logging.getLogger(__name__)
# Delete jobs a channel cleanup queues, and those hiding a listing queues. Hiding removes the
# listing's posts even when someone subscribed with 🔔, as the 🗑️ reaction does.
CLEANUP = {"reason": "cleanup"}
HIDDEN = {"reason": "hidden"}
MAX_HIDDEN_RETURNED = 500


def _time(value):
    if value is None:
        return None
    if isinstance(value, str):
        from datetime import datetime
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _item_json(item):
    """A listing's facts as the dashboard shows them. item is an Item or a dict of its columns."""
    get = item.get if isinstance(item, dict) else lambda name: getattr(item, name)
    return {"item_id": str(get("id")), "source": get("checker"), "external_id": get("item_id"),
            "title": get("title"), "price": get("price"), "buyout_price": get("buyout_price"),
            "stock": get("stock"), "image_url": get("image_url") or None, "url": get("url") or None,
            "end_time": _time(get("end_time")), "muted": bool(get("muted")),
            "updated_at": _time(get("updated_at")), "last_seen_at": _time(get("last_seen_at"))}


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

    @staticmethod
    def _blacklist(item_id, channel_id):
        Blacklist.insert(item=item_id, channel_id=channel_id).on_conflict_ignore().execute()
        DeliveryJob.update(status="cancelled").where(
            DeliveryJob.item == item_id, DeliveryJob.kind == "channel",
            DeliveryJob.destination_id == channel_id, DeliveryJob.status.in_(("pending", "failed"))).execute()

    async def blacklist_item(self, item_id, channel_id):
        def create():
            with database.atomic():
                self._blacklist(item_id, channel_id)
        await self._call("blacklist_item", create)

    async def hide_item(self, item_id, channel_id):
        """Hide a listing in a channel, as the 🗑️ reaction does, and queue the removal of its posts there.

        Returns how many posts were queued for removal.
        """
        def hide():
            with database.atomic("IMMEDIATE"):
                self._blacklist(item_id, channel_id)
                rows = list(live_posts(channel_id).select(Message.message_id, Message.item)
                            .where(Message.item == item_id, Message.message_id.not_in(queued_removals())).tuples())
                return queue_removals(channel_id, rows, HIDDEN)
        return await self._call("hide_item", hide)

    async def unhide_item(self, item_id, channel_id):
        """Show a hidden listing in the channel again. It is not posted again until it changes."""
        return await self._call("unhide_item", lambda: bool(Blacklist.delete().where(
            Blacklist.item == item_id, Blacklist.channel_id == channel_id).execute()))

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
        """Posts and DMs first. Post removals from the dashboard come only when nothing else waits,
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
                    # Skip posts that are already gone, and keep posts someone subscribed to meanwhile,
                    # unless the listing was hidden: then its posts go like the 🗑️ reaction's.
                    allowed = (Message.select().where(Message.message_id == job.message_id, ~Message.deleted).exists()
                               and (json.loads(job.payload) == HIDDEN
                                    or not Notification.select().where(Notification.item == job.item_id).exists()))
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
            # backlog alerts are about posts and DMs that are late. The dashboard shows its progress.
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

    async def alert_guilds(self, channel_id):
        """The servers saved on a channel's alerts. Only for channels Discord says are gone."""
        return await self._call("alert_guilds", lambda: {row[0] for row in Alert.select(Alert.guild_id).where(
            Alert.channel_id == channel_id, Alert.guild_id.is_null(False)).tuples()})

    async def guild_summaries(self, guild_ids=None):
        """Server ID to its searches and its failed posts and DMs. None means every server with a search."""
        def select():
            alerts = Alert.select(Alert.id, Alert.guild_id).where(Alert.guild_id.is_null(False))
            if guild_ids is not None:
                alerts = alerts.where(Alert.guild_id.in_(list(guild_ids)))
            summary = {}
            for alert_id, guild_id in alerts.tuples():
                entry = summary.setdefault(guild_id, {"alert_ids": [], "failed_deliveries": 0})
                entry["alert_ids"].append(alert_id)
            failed = (DeliveryJob.select(Alert.guild_id, fn.COUNT(DeliveryJob.id)).join(Alert)
                      .where(DeliveryJob.status == "failed", DeliveryJob.kind != "delete",
                             Alert.guild_id.in_(list(summary))).group_by(Alert.guild_id))
            for guild_id, count in failed.tuples():
                summary[guild_id]["failed_deliveries"] = count
            return summary
        return await self._call("guild_summaries", select)

    async def search_counts(self, guild_id):
        """Channel ID to how many searches it has, for the alerts saved with this server."""
        return await self._call("search_counts", lambda: dict(
            Alert.select(Alert.channel_id, fn.COUNT(Alert.id)).where(Alert.guild_id == guild_id)
            .group_by(Alert.channel_id).tuples()))

    async def hidden_counts(self, channel_ids):
        def select():
            counts = {}
            for batch in chunked(sorted(channel_ids), 500):
                counts.update(Blacklist.select(Blacklist.channel_id, fn.COUNT(Blacklist.id))
                              .where(Blacklist.channel_id.in_(batch)).group_by(Blacklist.channel_id).tuples())
            return counts
        return await self._call("hidden_counts", select)

    async def hidden_items(self, channel_id, limit=MAX_HIDDEN_RETURNED):
        """The listings hidden in a channel, most recently changed first."""
        def select():
            query = (Item.select(Item).join(Blacklist).where(Blacklist.channel_id == channel_id)
                     .order_by(Item.updated_at.desc(), Item.id.desc()))
            return {"items": [_item_json(row) for row in query.limit(limit).dicts()], "total": query.count()}
        return await self._call("hidden_items", select)

    async def item_in_channel(self, item_id, channel_id):
        """True when the listing was posted, tracked or hidden in the channel, so it may be hidden there."""
        def select():
            in_channel = Alert.select(Alert.id).where(Alert.channel_id == channel_id)
            return (Message.select().where(Message.item == item_id, Message.channel_id == channel_id).exists()
                    or AlertItem.select().where(AlertItem.item == item_id, AlertItem.alert.in_(in_channel)).exists()
                    or Blacklist.select().where(Blacklist.item == item_id, Blacklist.channel_id == channel_id).exists())
        return await self._call("item_in_channel", select)

    async def item_in_guilds(self, item_id, guilds):
        """True when the listing was posted or tracked by a search in one of these servers."""
        def select():
            alerts = Alert.select(Alert.id).where(Alert.guild_id.in_(list(guilds)))
            return (Item.select().where(Item.id == item_id).exists() and (
                Message.select().where(Message.item == item_id, Message.alert.in_(alerts)).exists()
                or AlertItem.select().where(AlertItem.item == item_id, AlertItem.alert.in_(alerts)).exists()))
        return await self._call("item_in_guilds", select)

    async def channel_posts(self, channel_id, *, alert_id=None, before=None, limit=50, user_id=None):
        """The bot's live posts in a channel, newest first, a page at a time.

        Each post says whether its listing is hidden, how many people subscribed with 🔔 and, for
        user_id, whether that person did. Who the other subscribers are is never returned.
        """
        def select():
            query = live_posts(channel_id, alert_id)
            if before is not None:
                query = query.where(Message.message_id < before)
            rows = list(query.order_by(Message.message_id.desc()).limit(limit + 1).dicts())
            items = {row["item"] for row in rows[:limit]}
            subscribers = dict(Notification.select(Notification.item, fn.COUNT(Notification.id))
                               .where(Notification.item.in_(list(items))).group_by(Notification.item).tuples())
            mine = set() if user_id is None else {row[0] for row in Notification.select(Notification.item).where(
                Notification.item.in_(list(items)), Notification.user_id == user_id).tuples()}
            hidden = {row[0] for row in Blacklist.select(Blacklist.item).where(
                Blacklist.item.in_(list(items)), Blacklist.channel_id == channel_id).tuples()}
            posts = []
            for row in rows[:limit]:
                post = post_json(row)
                post.update({"message_id": str(row["message_id"]), "item_id": str(row["item"]),
                             "hidden": row["item"] in hidden, "subscribers": subscribers.get(row["item"], 0),
                             "subscribed_by_me": row["item"] in mine})
                posts.append(post)
            return {"posts": posts, "next_before": str(rows[limit - 1]["message_id"]) if len(rows) > limit else None}
        return await self._call("channel_posts", select)

    async def channel_removable_posts(self, channel_id, days=None, alert_id=None, limit=POST_REMOVAL_SCAN_LIMIT):
        """A channel's live posts for a cleanup, newest first. alert_id narrows it to one search's posts."""
        removal_days(days)

        def select():
            query = live_posts(channel_id, alert_id, days)
            rows = list(query.order_by(Message.message_id.desc()).limit(limit).dicts())
            return {"posts": [post_json(row) for row in rows],
                    "total": query.count() if len(rows) >= limit else len(rows)}
        return await self._call("channel_removable_posts", select)

    async def queue_channel_removals(self, channel_id, message_ids):
        """Queue the deletion of chosen posts in a channel. Posts that are gone, have a 🔔 subscriber
        or are already queued are skipped, as in a search's removal. Returns how many were queued."""
        def queue():
            with database.atomic("IMMEDIATE"):
                rows = list(live_posts(channel_id, message_ids=message_ids).select(Message.message_id, Message.item)
                            .where(Message.item.not_in(Notification.select(Notification.item)),
                                   Message.message_id.not_in(queued_removals())).tuples())
                return queue_removals(channel_id, rows, CLEANUP)
        return await self._call("queue_channel_removals", queue)

    async def channel_removal_status(self, channel_id):
        """Progress of the channel's newest cleanup run."""
        return await self._call("channel_removal_status", lambda: removal_run(DeliveryJob.select().where(
            DeliveryJob.destination_id == channel_id, DeliveryJob.kind == "delete",
            DeliveryJob.payload == json.dumps(CLEANUP))))

    async def subscriptions(self, user_id):
        """The listings one person gets 🔔 DMs for, with where each was posted. Nobody else's."""
        def select():
            items = list(Item.select(Item).join(Notification).where(Notification.user_id == user_id)
                         .order_by(Item.updated_at.desc(), Item.id.desc()).dicts())
            ids = [row["id"] for row in items]
            posts = {}
            for batch in chunked(ids, 500):
                query = (Message.select(Message.item, Message.channel_id, fn.MAX(Message.message_id), Alert.guild_id,
                                        Alert.search_query)
                         .join(Alert, JOIN.LEFT_OUTER).where(Message.item.in_(batch))
                         .group_by(Message.item, Message.channel_id))
                for item, channel, message, guild, query_text in query.tuples():
                    posts.setdefault(item, []).append({"channel_id": str(channel), "message_id": str(message),
                                                       "guild_id": str(guild) if guild else None,
                                                       "search_query": query_text})
            pending = dict(DeliveryJob.select(DeliveryJob.item, fn.COUNT(DeliveryJob.id)).where(
                DeliveryJob.kind == "dm", DeliveryJob.destination_id == user_id,
                DeliveryJob.status.in_(("pending", "failed"))).group_by(DeliveryJob.item).tuples())
            return [{**_item_json(row), "posts": posts.get(row["id"], []), "waiting_dms": pending.get(row["id"], 0)}
                    for row in items]
        return await self._call("subscriptions", select)

    async def listing_items(self, listings, user_id=None):
        """(source, external ID) to the stored listing's ID and, for user_id, whether they subscribed."""
        def select():
            found = {}
            for batch in chunked(sorted(set(listings)), 200):
                condition = None
                for source, external_id in batch:
                    match = (Item.checker == source) & (Item.item_id == external_id)
                    condition = match if condition is None else condition | match
                for item_id, source, external_id in Item.select(Item.id, Item.checker, Item.item_id).where(
                        condition).tuples():
                    found[(source, external_id)] = {"item_id": str(item_id), "subscribed": False}
            if user_id is not None and found:
                ids = [int(value["item_id"]) for value in found.values()]
                mine = {row[0] for row in Notification.select(Notification.item).where(
                    Notification.item.in_(ids), Notification.user_id == user_id).tuples()}
                for value in found.values():
                    value["subscribed"] = int(value["item_id"]) in mine
            return found
        return await self._call("listing_items", select)

    async def delivery_backlog(self, alert_ids):
        """Alert ID to its posts and DMs waiting to be sent or failed, and the age of the oldest waiting one."""
        def select():
            now = utcnow()
            backlog = {alert_id: {"pending": 0, "failed": 0, "oldest_pending_seconds": None} for alert_id in alert_ids}
            for batch in chunked(sorted(alert_ids), 500):
                query = (DeliveryJob.select(DeliveryJob.alert, DeliveryJob.status, fn.COUNT(DeliveryJob.id),
                                            fn.MIN(DeliveryJob.created_at))
                         .where(DeliveryJob.alert.in_(batch), DeliveryJob.kind != "delete",
                                DeliveryJob.status.in_(("pending", "failed")))
                         .group_by(DeliveryJob.alert, DeliveryJob.status))
                for alert_id, status, count, oldest in query.tuples():
                    entry = backlog[alert_id]
                    entry[status] = count
                    if status == "pending" and oldest is not None:
                        if isinstance(oldest, str):
                            from datetime import datetime
                            oldest = datetime.fromisoformat(oldest)
                        entry["oldest_pending_seconds"] = max(0, round((now - oldest).total_seconds()))
            return backlog
        return await self._call("delivery_backlog", select)

    async def alert_usage(self, alert_id):
        """What unregistering a search touches, for the dashboard to explain before it happens."""
        def select():
            from models import CandidateObservation, ReviewRuleVersion
            return {
                "posts": Message.select().where(Message.alert == alert_id, ~Message.deleted).count(),
                "waiting_posts": DeliveryJob.select().where(
                    DeliveryJob.alert == alert_id, DeliveryJob.kind != "delete",
                    DeliveryJob.status.in_(("pending", "failed"))).count(),
                "rule_versions": ReviewRuleVersion.select().where(ReviewRuleVersion.alert == alert_id).count(),
                "archived": CandidateObservation.select().where(CandidateObservation.alert == alert_id).count(),
                "legacy_filters": Filter.select().where(Filter.alert == alert_id).count(),
            }
        return await self._call("alert_usage", select)

