"""The dashboard's server management: searches, a channel's posts and hidden listings, cleanup,
your own 🔔 notifications and the bot's status.

Each change does what the matching slash command or reaction does, with the same repository
functions and the same checks. Every route only reaches the servers the person may see. A
channel ID from the browser is looked up with Discord first: the alerts table alone never
decides which server a channel is in, except for a channel Discord says is gone. A change needs
Manage Channels in that channel, counting its overwrites, as the slash commands check it.
"""
import asyncio
import logging
import time

from aiohttp import web
import hikari

from channel_maintenance import MAX_DELETE_COUNT, Progress, add_cleanup_reactions, delete_recent_bot_posts
from commands.base import HISTORY_SCAN_LIMIT, clean_search_query
from dashboard_auth import DiscordUnavailable, can_manage
from discord_directory import Lookup, member_permissions, posting, sidebar
from review_repository import POST_REMOVAL_LIMIT, ReviewNotFound, ReviewValidation, removal_days
from review_service import identifier


logger = logging.getLogger(__name__)
SCAN_ACTIONS = {"delete_bot_posts", "add_reactions"}
POSTS_PAGE = 50


class ChannelNotFound(ReviewNotFound):
    """Raised alike for a channel that does not exist and one in a server the person may not see."""

    def __init__(self):
        super().__init__("Channel not found")


def _name(lookup, channel_id):
    return f"#{lookup.channel.name}" if lookup.channel is not None else f"channel {channel_id}"


class Management:
    def __init__(self, server, bot=None):
        """server is the DashboardServer. bot is the running GatewayBot, for history scans; None without one."""
        self.server, self.bot = server, bot
        self.repository = server.repository
        # Channel ID to the newest history scan there: what it does, how far it got, and how it ended.
        self.scans = {}
        self.scan_tasks = set()

    @property
    def directory(self):
        return self.server.directory

    def routes(self):
        return [
            web.get("/api/guilds", self.guilds, name="guilds"),
            web.get("/api/guilds/{guild}/channels", self.channels, name="guild_channels"),
            web.get("/api/guilds/{guild}/status", self.status, name="guild_status"),
            web.post("/api/alerts", self.register, name="alert_register"),
            web.get("/api/alerts/{id}", self.alert, name="alert"),
            web.delete("/api/alerts/{id}", self.unregister, name="alert_unregister"),
            web.delete("/api/alerts/{id}/legacy-filters/{filter}", self.delete_filter, name="legacy_filter_delete"),
            web.get("/api/channels/{channel}/posts", self.posts, name="channel_posts"),
            web.get("/api/channels/{channel}/hidden", self.hidden, name="hidden"),
            web.put("/api/channels/{channel}/hidden/{item}", self.hide, name="hide"),
            web.delete("/api/channels/{channel}/hidden/{item}", self.unhide, name="unhide"),
            web.post("/api/channels/{channel}/posts/removal-preview", self.cleanup_preview, name="cleanup_preview"),
            web.post("/api/channels/{channel}/posts/removal", self.cleanup, name="cleanup"),
            web.get("/api/channels/{channel}/posts/removal", self.cleanup_status, name="cleanup_status"),
            web.post("/api/channels/{channel}/history-scan", self.start_scan, name="history_scan"),
            web.get("/api/channels/{channel}/history-scan", self.scan_status, name="history_scan_status"),
            web.get("/api/me/notifications", self.notifications, name="notifications"),
            web.put("/api/me/notifications/{item}", self.subscribe, name="subscribe"),
            web.delete("/api/me/notifications/{item}", self.unsubscribe, name="unsubscribe"),
        ]

    async def close(self):
        for task in list(self.scan_tasks):
            task.cancel()
        await asyncio.gather(*self.scan_tasks, return_exceptions=True)

    # Scope.

    def guild_in_scope(self, request, raw):
        guild_id = identifier(raw, "guild_id")
        guilds = self.server.guilds(request)
        if guilds is not None and guild_id not in guilds:
            raise ReviewNotFound("Server not found")
        return guild_id

    async def lookup(self, channel_id):
        return await self.directory.find(channel_id) if self.directory.available else Lookup()

    async def channel_in_scope(self, request, raw, *, change=False, gone_ok=False):
        """(server ID, Lookup) for a channel in one of the person's servers; ChannelNotFound otherwise.

        change: the request changes something, so the person needs Manage Channels in the channel.
        gone_ok: the change also makes sense for a channel Discord says is deleted, such as
        unregistering its searches. Its saved alerts then say which server it was in, and the
        server-wide Manage Channels of the sign-in counts.
        """
        channel_id = identifier(raw, "channel_id")
        guilds = self.server.guilds(request)
        lookup = await self.lookup(channel_id)
        if lookup.channel is not None:
            if guilds is not None and lookup.guild.id not in guilds:
                raise ChannelNotFound()
            if change:
                self.require_manage(request, lookup)
            return lookup.guild.id, lookup
        saved = await self.repository.alert_guilds(channel_id)
        permitted = saved if guilds is None else saved & guilds
        if not permitted:
            raise ChannelNotFound()
        if change and not (lookup.deleted and gone_ok):
            raise web.HTTPConflict(reason=(
                "Discord says this channel was deleted." if lookup.deleted else
                "Changes need the bot's token, to check the channel with Discord." if not self.directory.available
                else "Discord does not show this channel to the bot, so it cannot be changed from here."))
        return min(permitted), lookup

    def require_manage(self, request, lookup):
        """Manage Channels in this channel, with its overwrites, as the slash commands need it."""
        session = request[self.server.session_key]
        if session.user is None:
            # The access key opens everything; there is no Discord user to check.
            return
        member = (session.members or {}).get(lookup.guild.id)
        permissions = member_permissions(lookup.guild, lookup.channel, int(session.user["id"]),
                                         member.role_ids if member else (), member.timed_out if member else False)
        if member is None or not can_manage(permissions):
            raise web.HTTPForbidden(reason=f"You need the Manage Channels permission in #{lookup.channel.name} "
                                           "to change it.")

    def can_manage_here(self, request, guild, channel):
        session = request[self.server.session_key]
        if session.user is None:
            return True
        member = (session.members or {}).get(guild.id)
        return member is not None and can_manage(member_permissions(
            guild, channel, int(session.user["id"]), member.role_ids, member.timed_out))

    def log(self, event, actor, guild_id, channel_id, **fields):
        """Log a change like the slash command logs it, with who made it. actor is a request or
        the actor fields taken from one."""
        actor = self.server.actor(actor) if isinstance(actor, web.Request) else actor
        logger.info(event, extra={"fields": {
            "channel_id": int(channel_id), "guild_id": int(guild_id) if guild_id is not None else None,
            **actor, "via": "dashboard", **fields}})

    def user_id(self, request):
        user = request[self.server.session_key].user
        if user is None:
            raise web.HTTPForbidden(reason="Notifications are personal, so they need Discord sign-in.")
        return int(user["id"])

    # Servers.

    async def guilds(self, request):
        """The servers for the server list, with how many searches each has and whether one has a problem."""
        session = request[self.server.session_key]
        if session.guilds is not None:
            servers = [dict(guild) for guild in session.guilds.values()]
        else:
            try:
                servers = await self.directory.servers() if self.directory.available else []
            except DiscordUnavailable:
                servers = []
        summaries = await self.repository.guild_summaries(None if session.guilds is None else set(session.guilds))
        known = {server["id"] for server in servers}
        servers += [{"id": str(guild_id), "name": None, "icon_url": None}
                    for guild_id in summaries if str(guild_id) not in known]
        runtime = self.server.runtime
        failing = set()
        if runtime is not None:
            failing = {alert_id for (alert_id, _), result in runtime.check_results.items()
                       if result["outcome"] != "success"}
        for server in servers:
            summary = summaries.get(int(server["id"]), {"alert_ids": [], "failed_deliveries": 0})
            server["searches"] = len(summary["alert_ids"])
            server["failing_searches"] = len(failing & set(summary["alert_ids"]))
            server["failed_deliveries"] = summary["failed_deliveries"]
        servers.sort(key=lambda server: ((server["name"] or "").casefold() or "￿", server["id"]))
        return web.json_response({"guilds": servers})

    async def channels(self, request):
        """The server's channel list as Discord shows it, with searches and hidden listings per channel."""
        guild_id = self.guild_in_scope(request, request.match_info["guild"])
        searches = await self.repository.search_counts(guild_id)
        try:
            guild = await self.directory.guild(guild_id) if self.directory.available else None
            unavailable = False
        except DiscordUnavailable:
            guild, unavailable = None, True
        if guild is None:
            # Nothing from Discord: the saved channels by ID, so their searches stay reachable.
            hidden = await self.repository.hidden_counts(set(searches))
            return web.json_response({
                "guild": {"id": str(guild_id), "name": None, "icon_url": None}, "source": "none",
                "discord_unavailable": unavailable, "sections": [],
                "unknown": [{"id": str(channel_id), "deleted": False, "searches": count,
                             "hidden": hidden.get(channel_id, 0)} for channel_id, count in sorted(searches.items())]})
        hidden = await self.repository.hidden_counts(set(guild.channels) | set(searches))
        counts = {channel_id: {"searches": searches.get(channel_id, 0), "hidden": hidden.get(channel_id, 0)}
                  for channel_id in set(searches) | set(hidden)}
        outside = {}
        for channel_id in counts:
            if channel_id not in guild.channels:
                try:
                    outside[channel_id] = await self.directory.find(channel_id)
                except DiscordUnavailable:
                    outside[channel_id] = Lookup()
        result = sidebar(guild, await self.directory.bot_id(), counts, outside)
        channels = {**guild.channels, **{key: value.channel for key, value in outside.items() if value.channel}}
        for section in result["sections"]:
            for row in section["channels"]:
                for entry in (row, *row["threads"]):
                    entry["can_manage"] = self.can_manage_here(request, guild, channels[int(entry["id"])])
        result.update(guild={"id": str(guild.id), "name": guild.name, "icon_url": guild.icon_url},
                      discord_unavailable=False)
        return web.json_response(result)

    async def status(self, request):
        """Each search's last checks, its counts and its posts and DMs waiting, plus the bot's state."""
        guild_id = self.guild_in_scope(request, request.match_info["guild"])
        alerts = (await self.repository.review_alerts(guilds=frozenset({guild_id})))["alerts"]
        backlog = await self.repository.delivery_backlog([int(alert["id"]) for alert in alerts])
        names = await self.server.channel_names(alerts)
        runtime = self.server.runtime
        state = runtime.status() if runtime is not None else None
        searches = []
        for alert in alerts:
            searches.append({**alert, "channel_name": names.get(alert["channel_id"]),
                             "checks": state["checks"].get(int(alert["id"]), []) if state else None,
                             "backlog": backlog[int(alert["id"])]})
        if state is not None:
            state.pop("checks")
        settings = self.server.settings
        return web.json_response({
            "bot_running": self.server.bot_running, "bot": state, "enabled_sources": list(settings.enabled_sources),
            "interval_seconds": settings.interval, "searches": searches,
            "totals": {"searches": len(searches),
                       "pending": sum(search["backlog"]["pending"] for search in searches),
                       "failed": sum(search["backlog"]["failed"] for search in searches)}})

    # Searches.

    async def register(self, request):
        """/register for a channel picked in the dashboard."""
        data = await self.server.body(request)
        guild_id, lookup = await self.channel_in_scope(request, data.get("channel_id"), change=True)
        search_query = clean_search_query(data.get("search_query"))
        check = posting(lookup.guild, lookup.channel, await self.directory.bot_id())
        if not check["can_post"]:
            reasons = check["problems"] + ([f"The bot needs {', '.join(check['missing'])} there."]
                                           if check["missing"] else [])
            raise ReviewValidation(f"The bot cannot post in #{lookup.channel.name}. " + " ".join(reasons))
        channel_id = lookup.channel.id
        if not await self.repository.register_alert(channel_id, search_query, guild_id=guild_id):
            raise web.HTTPConflict(reason=f"A search for {search_query} already exists in #{lookup.channel.name}.")
        alert = next(row for row in await self.repository.list_alerts(channel_id=channel_id)
                     if row["search_query"] == search_query)
        self.log("alert_registered", request, guild_id, channel_id, alert_id=alert["id"])
        result = await self.repository.review_alert(alert["id"], self.server.guilds(request))
        return web.json_response({**result, "channel_name": lookup.channel.name}, status=201)

    async def alert(self, request):
        """One search, its channel, and what unregistering it would touch."""
        alert_id = identifier(request.match_info["id"], "alert_id")
        alert = await self.repository.review_alert(alert_id, self.server.guilds(request))
        try:
            lookup = await self.lookup(int(alert["channel_id"]))
        except DiscordUnavailable:
            lookup = Lookup()
        channel = None
        if lookup.channel is not None:
            channel = {"name": lookup.channel.name, "kind": lookup.channel.kind,
                       "posting": posting(lookup.guild, lookup.channel, await self.directory.bot_id()),
                       "can_manage": self.can_manage_here(request, lookup.guild, lookup.channel)}
        return web.json_response({"alert": alert, "usage": await self.repository.alert_usage(alert_id),
                                  "channel": channel, "channel_deleted": lookup.deleted})

    async def unregister(self, request):
        """/unregister. Posts stay in Discord; rule versions and the archive are kept without the search."""
        alert_id = identifier(request.match_info["id"], "alert_id")
        alert = await self.repository.review_alert(alert_id, self.server.guilds(request))
        guild_id, _ = await self.channel_in_scope(request, alert["channel_id"], change=True, gone_ok=True)
        if not await self.repository.unregister_alert(int(alert["channel_id"]), alert["search_query"]):
            raise ReviewNotFound("Alert no longer exists")
        self.log("alert_unregistered", request, guild_id, alert["channel_id"], alert_id=alert["id"])
        return web.json_response({"unregistered": True})

    async def delete_filter(self, request):
        """/filters delete for one of the search's legacy filters."""
        alert_id = identifier(request.match_info["id"], "alert_id")
        filter_id = identifier(request.match_info["filter"], "filter_id")
        guilds = self.server.guilds(request)
        alert = await self.repository.review_alert(alert_id, guilds)
        if filter_id not in {row["id"] for row in await self.repository.review_filters(alert_id, guilds)}:
            raise ReviewNotFound("Filter not found")
        guild_id, _ = await self.channel_in_scope(request, alert["channel_id"], change=True, gone_ok=True)
        if not await self.repository.delete_filter(int(alert["channel_id"]), filter_id):
            raise ReviewNotFound("Filter not found")
        self.log("filter_deleted", request, guild_id, alert["channel_id"], filter_id=filter_id)
        return web.json_response({"deleted": True})

    # A channel's posts and hidden listings.

    async def posts(self, request):
        _, lookup = await self.channel_in_scope(request, request.match_info["channel"])
        channel_id = identifier(request.match_info["channel"], "channel_id")
        query = request.query
        alert_id = identifier(query["alert_id"], "alert_id") if query.get("alert_id") else None
        before = identifier(query["before"], "before") if query.get("before") else None
        user = request[self.server.session_key].user
        result = await self.repository.channel_posts(channel_id, alert_id=alert_id, before=before, limit=POSTS_PAGE,
                                                     user_id=int(user["id"]) if user else None)
        return web.json_response({**result, "notifications": user is not None})

    async def hidden(self, request):
        await self.channel_in_scope(request, request.match_info["channel"])
        return web.json_response(await self.repository.hidden_items(
            identifier(request.match_info["channel"], "channel_id")))

    async def hide(self, request):
        """What the 🗑️ reaction does: hide the listing in this channel and remove its posts there."""
        guild_id, lookup = await self.channel_in_scope(request, request.match_info["channel"], change=True)
        channel_id, item_id = lookup.channel.id, identifier(request.match_info["item"], "item_id")
        if not await self.repository.item_in_channel(item_id, channel_id):
            raise ReviewNotFound("Listing not found")
        queued = await self.repository.hide_item(item_id, channel_id)
        self.log("item_blacklisted", request, guild_id, channel_id, item_id=item_id, posts_queued=queued)
        return web.json_response({"hidden": True, "posts_queued": queued, "bot_running": self.server.bot_running})

    async def unhide(self, request):
        guild_id, _ = await self.channel_in_scope(request, request.match_info["channel"], change=True, gone_ok=True)
        channel_id, item_id = (identifier(request.match_info[name], f"{name}_id") for name in ("channel", "item"))
        if not await self.repository.unhide_item(item_id, channel_id):
            raise ReviewNotFound("Listing not found")
        self.log("item_unhidden", request, guild_id, channel_id, item_id=item_id)
        return web.json_response({"hidden": False})

    # Cleanup.

    async def cleanup_preview(self, request):
        """The channel's posts a cleanup would remove. Nothing changes."""
        await self.channel_in_scope(request, request.match_info["channel"])
        channel_id = identifier(request.match_info["channel"], "channel_id")
        data = await self.server.body(request)
        days = data.get("days", 30)
        if isinstance(days, bool) or not (days is None or isinstance(days, int)):
            raise ReviewValidation("Choose posts from the last 7, 30 or 90 days, or all posts")
        removal_days(days)
        alert_id = identifier(data["alert_id"], "alert_id") if data.get("alert_id") else None
        found = await self.repository.channel_removable_posts(channel_id, days, alert_id)
        removable = [post for post in found["posts"] if not post["subscribed"] and not post["queued"]]
        run = removable[:POST_REMOVAL_LIMIT]
        return web.json_response({
            "days": days, "posts_in_range": found["total"], "removable_total": len(removable),
            "limit": POST_REMOVAL_LIMIT, "bot_running": self.server.bot_running,
            "kept": {"subscribed": sum(post["subscribed"] for post in found["posts"]),
                     "queued": sum(post["queued"] and not post["subscribed"] for post in found["posts"])},
            "posts": [{"message_id": str(post["message_id"]), "posted_at": post["posted_at"],
                       "alert_id": post["alert_id"], "title": post["listing"]["title"],
                       "source": post["listing"]["source"], "external_id": post["listing"]["id"],
                       "price": post["listing"]["price"], "image_url": post["listing"]["image_url"],
                       "url": post["listing"]["url"]} for post in run]})

    async def cleanup(self, request):
        """Queue the removal of the chosen posts. The delivery worker removes them, 100 at a time when it can."""
        guild_id, lookup = await self.channel_in_scope(request, request.match_info["channel"], change=True)
        data = await self.server.body(request)
        values = data.get("message_ids")
        if not isinstance(values, list) or not 1 <= len(values) <= POST_REMOVAL_LIMIT:
            raise ReviewValidation(f"Choose between 1 and {POST_REMOVAL_LIMIT} posts")
        message_ids = sorted({identifier(value, "message_id") for value in values})
        queued = await self.repository.queue_channel_removals(lookup.channel.id, message_ids)
        self.log("post_removal_queued", request, guild_id, lookup.channel.id, reason="cleanup", queued=queued,
                 skipped=len(message_ids) - queued)
        return web.json_response({"queued": queued, "skipped": len(message_ids) - queued,
                                  "bot_running": self.server.bot_running})

    async def cleanup_status(self, request):
        await self.channel_in_scope(request, request.match_info["channel"])
        result = await self.repository.channel_removal_status(identifier(request.match_info["channel"], "channel_id"))
        return web.json_response({**result, "bot_running": self.server.bot_running})

    async def start_scan(self, request):
        """/cleanup or /reacttocleanup over the channel's latest messages, run in the background."""
        guild_id, lookup = await self.channel_in_scope(request, request.match_info["channel"], change=True)
        data = await self.server.body(request)
        action = data.get("action")
        if action not in SCAN_ACTIONS:
            raise ReviewValidation("Choose delete_bot_posts or add_reactions")
        count = data.get("count", 10)
        if action == "delete_bot_posts" and (isinstance(count, bool) or not isinstance(count, int)
                                             or not 1 <= count <= MAX_DELETE_COUNT):
            raise ReviewValidation(f"Count must be between 1 and {MAX_DELETE_COUNT}.")
        bot_user = self.bot.get_me() if self.bot is not None else None
        if bot_user is None:
            raise web.HTTPConflict(reason="This reads the channel's messages, so it needs the bot running and "
                                          "connected to Discord.")
        channel_id = lookup.channel.id
        current = self.scans.get(channel_id)
        if current is not None and current["state"] == "running":
            raise web.HTTPConflict(reason="A scan of this channel is already running.")
        progress = Progress()
        scan = {"action": action, "count": count if action == "delete_bot_posts" else None, "state": "running",
                "started_at": time.time(), "finished_at": None, "progress": progress,
                "history_limit": HISTORY_SCAN_LIMIT}
        self.scans[channel_id] = scan
        task = asyncio.create_task(self._scan(self.server.actor(request), guild_id, channel_id, int(bot_user.id), scan),
                                   name="auction-bot:dashboard-history-scan")
        self.scan_tasks.add(task)
        task.add_done_callback(self.scan_tasks.discard)
        return web.json_response({"scan": self._scan_json(scan)}, status=202)

    async def _scan(self, actor, guild_id, channel_id, bot_id, scan):
        rest, progress = self.bot.rest, scan["progress"]
        event = "cleanup_completed" if scan["action"] == "delete_bot_posts" else "cleanup_reactions_completed"
        try:
            if scan["action"] == "delete_bot_posts":
                await delete_recent_bot_posts(rest, self.repository, bot_id, channel_id, scan["count"], progress)
            else:
                await add_cleanup_reactions(rest, self.repository, bot_id, channel_id, progress)
            scan["state"] = "done"
        except asyncio.CancelledError:
            scan["state"] = "failed"
            raise
        except Exception as error:
            scan["state"] = "forbidden" if isinstance(error, hikari.ForbiddenError) else "failed"
            logger.warning(event.replace("completed", "failed"), exc_info=True,
                           extra={"fields": {"channel_id": channel_id, "via": "dashboard"}})
        finally:
            scan["finished_at"] = time.time()
        field = "deleted" if scan["action"] == "delete_bot_posts" else "added"
        self.log(event, actor, guild_id, channel_id, **{field: progress.done}, history_limit=HISTORY_SCAN_LIMIT)

    @staticmethod
    def _scan_json(scan):
        return {key: value for key, value in scan.items() if key != "progress"} | {"done": scan["progress"].done}

    async def scan_status(self, request):
        await self.channel_in_scope(request, request.match_info["channel"])
        scan = self.scans.get(identifier(request.match_info["channel"], "channel_id"))
        return web.json_response({"scan": self._scan_json(scan) if scan else None,
                                  "available": self.bot is not None and self.bot.get_me() is not None})

    # Your own 🔔 notifications.

    async def notifications(self, request):
        """The listings you get DMs for. Posts in servers you may not see are left out; the listing is not."""
        user_id = self.user_id(request)
        guilds = self.server.guilds(request)
        items = await self.repository.subscriptions(user_id)
        for item in items:
            item["posts"] = [post for post in item["posts"]
                             if post["guild_id"] is not None and (guilds is None or int(post["guild_id"]) in guilds)]
        names = await self.server.channel_names([post for item in items for post in item["posts"]])
        for item in items:
            for post in item["posts"]:
                post["channel_name"] = names.get(post["channel_id"])
        return web.json_response({"items": items})

    async def subscribe(self, request):
        """What the 🔔 reaction does, for a listing posted or tracked in one of your servers."""
        user_id = self.user_id(request)
        item_id = identifier(request.match_info["item"], "item_id")
        guilds = self.server.guilds(request)
        if not await self.repository.item_in_guilds(item_id, guilds):
            raise ReviewNotFound("Listing not found")
        created = await self.repository.subscribe(item_id, user_id)
        logger.info("notification_subscribed", extra={"fields": {
            "item_id": item_id, "user_id": user_id, **self.server.actor(request), "via": "dashboard"}})
        return web.json_response({"subscribed": True, "created": created})

    async def unsubscribe(self, request):
        user_id = self.user_id(request)
        item_id = identifier(request.match_info["item"], "item_id")
        if not await self.repository.unsubscribe(item_id, user_id):
            raise ReviewNotFound("Listing not found")
        logger.info("notification_unsubscribed", extra={"fields": {
            "item_id": item_id, "user_id": user_id, **self.server.actor(request), "via": "dashboard"}})
        return web.json_response({"subscribed": False})
