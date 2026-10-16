"""What the dashboard knows about the bot's Discord servers: channels, threads, and what the bot may do there.

In the bot this comes from the gateway cache, which Discord keeps current with channel, role and
member updates. The standalone dashboard has no gateway and uses the REST API with the bot's
token. So does the bot for a server that is not in its cache yet: right after connecting, Discord
sends each server's channels a few seconds after the bot is ready. A REST answer is kept for
TTL_SECONDS, so a page that asks several times costs Discord one round of calls per server.

A channel only counts as deleted when Discord answers that it does not exist. A channel that is
missing from the cache, or that the bot may not see, is unknown instead.
"""
import asyncio
from dataclasses import dataclass, field
import time

import hikari

from dashboard_auth import UNAVAILABLE, DiscordUnavailable, describe, guild_permissions


P = hikari.Permissions
T = hikari.ChannelType
TTL_SECONDS = 60
# A lookup of a single channel, found or not, is kept longer: a deleted channel stays deleted.
CHANNEL_TTL_SECONDS = 300
TIMEOUT_SECONDS = 10
# What the bot needs to post a search's listings: the post with its embed, then the 🗑️ and 🔔
# reactions. Discord also wants Read Message History before it lets the bot add a reaction.
POST = P.VIEW_CHANNEL | P.SEND_MESSAGES | P.EMBED_LINKS | P.ADD_REACTIONS | P.READ_MESSAGE_HISTORY
# In a thread, Send Messages in Threads takes the place of Send Messages.
THREAD_POST = (POST & ~P.SEND_MESSAGES) | P.SEND_MESSAGES_IN_THREADS
# With Manage Messages the bot removes up to 100 recent posts per request; without it, one at a time.
BULK_DELETE = P.MANAGE_MESSAGES
# In the order Discord's own permission list shows them.
NAMES = {P.VIEW_CHANNEL: "View Channel", P.SEND_MESSAGES: "Send Messages",
         P.SEND_MESSAGES_IN_THREADS: "Send Messages in Threads", P.EMBED_LINKS: "Embed Links",
         P.ADD_REACTIONS: "Add Reactions", P.READ_MESSAGE_HISTORY: "Read Message History",
         P.MANAGE_MESSAGES: "Manage Messages", P.MANAGE_THREADS: "Manage Threads",
         P.MANAGE_CHANNELS: "Manage Channels"}
# Without Send Messages, Discord also takes these away in a text channel.
NEEDS_SEND = P.MENTION_ROLES | P.SEND_TTS_MESSAGES | P.ATTACH_FILES | P.EMBED_LINKS
KINDS = {T.GUILD_CATEGORY: "category", T.GUILD_TEXT: "text", T.GUILD_NEWS: "announcement",
         T.GUILD_FORUM: "forum", T.GUILD_MEDIA: "media", T.GUILD_VOICE: "voice", T.GUILD_STAGE: "stage",
         T.GUILD_PUBLIC_THREAD: "thread", T.GUILD_NEWS_THREAD: "thread", T.GUILD_PRIVATE_THREAD: "private_thread"}
THREADS = {"thread", "private_thread"}
# Where a search can post. Forums and media channels only take posts that start a thread, and
# voice and stage chats are left out because nobody reads listings there.
POSTABLE = {"text", "announcement", *THREADS}
# Discord's sidebar lists these above voice and stage channels in each category.
TEXT_LIKE = {"text", "announcement", "forum", "media"}


@dataclass(frozen=True)
class Overwrite:
    """A channel's permission overwrite for one role (or @everyone) or one member."""
    role: bool
    allow: P = P.NONE
    deny: P = P.NONE


@dataclass(frozen=True)
class Channel:
    id: int
    guild_id: int
    name: str
    kind: str
    position: int = 0
    parent_id: int | None = None
    # Role or member ID to its overwrite. Threads have none; they use their parent's.
    overwrites: dict = field(default_factory=dict, compare=False)
    archived: bool = False
    locked: bool = False
    # For a private thread: whether the bot was added to it, or None when that is unknown.
    joined: bool | None = None


@dataclass
class Guild:
    id: int
    name: str
    icon_url: str | None
    owner_id: int
    # Role ID to what the role allows. The @everyone role has the server's ID.
    roles: dict
    # Channel ID to Channel, threads included.
    channels: dict
    bot_roles: tuple
    bot_timed_out: bool
    # "gateway" or "rest".
    source: str


@dataclass(frozen=True)
class Lookup:
    """One channel ID looked up: its server and channel, or why there is none."""
    guild: Guild | None = None
    channel: Channel | None = None
    # True when Discord answered that the channel does not exist. False when it is only unknown.
    deleted: bool = False


def channel_permissions(base, guild_id, member_id, role_ids, overwrites):
    """A member's permissions in a channel, from their server-wide permissions and its overwrites.

    The order is Discord's: the @everyone overwrite, then every role overwrite together (denies,
    then allows), then the member's own overwrite. Administrators keep every permission, and
    without View Channel nothing else counts.
    """
    if base & P.ADMINISTRATOR:
        return P.all_permissions()
    permissions = base
    everyone = overwrites.get(guild_id)
    if everyone is not None:
        permissions = (permissions & ~everyone.deny) | everyone.allow
    allow = deny = P.NONE
    for role_id in role_ids:
        # Members' role lists can include @everyone, whose overwrite was applied above.
        overwrite = overwrites.get(role_id) if role_id != guild_id else None
        if overwrite is not None and overwrite.role:
            allow, deny = allow | overwrite.allow, deny | overwrite.deny
    permissions = (permissions & ~deny) | allow
    own = overwrites.get(member_id)
    if own is not None and not own.role:
        permissions = (permissions & ~own.deny) | own.allow
    if not permissions & P.VIEW_CHANNEL:
        return P.NONE
    return permissions


def member_permissions(guild, channel, member_id, role_ids, timed_out=False, implied=True):
    """What a member may do in a channel of the server. A thread uses its parent channel's overwrites.

    implied=False leaves out what Discord takes away without Send Messages, for saying which
    permission is missing.
    """
    base = guild_permissions(member_id, guild.owner_id, guild.id, guild.roles, role_ids, timed_out)
    target = guild.channels.get(channel.parent_id) if channel.kind in THREADS else channel
    permissions = channel_permissions(base, guild.id, member_id, role_ids, target.overwrites if target else {})
    if implied and channel.kind not in THREADS and not permissions & P.SEND_MESSAGES:
        permissions &= ~NEEDS_SEND
    return permissions


def names(permissions):
    return [name for permission, name in NAMES.items() if permissions & permission]


def posting(guild, channel, bot_id):
    """Whether the bot can post a search's listings in a channel, and if not, why not."""
    permissions = member_permissions(guild, channel, bot_id, guild.bot_roles, guild.bot_timed_out)
    thread = channel.kind in THREADS
    # Without View Channel nothing else counts, so that is the one to name.
    own = member_permissions(guild, channel, bot_id, guild.bot_roles, guild.bot_timed_out, implied=False)
    missing = names(P.VIEW_CHANNEL if not own & P.VIEW_CHANNEL else (THREAD_POST if thread else POST) & ~own)
    problems = []
    if channel.kind not in POSTABLE:
        problems.append("Searches can only post in text channels, announcement channels and threads.")
    if thread and channel.locked and not permissions & P.MANAGE_THREADS:
        problems.append("The thread is locked.")
    if channel.kind == "private_thread" and channel.joined is False and not permissions & P.MANAGE_THREADS:
        problems.append("The bot has not been added to this private thread.")
    return {"can_post": not missing and not problems, "missing": missing, "problems": problems,
            "bulk_delete": bool(permissions & BULK_DELETE),
            "read_history": bool(permissions & P.READ_MESSAGE_HISTORY)}


def discord_order(channels):
    """Channels the way Discord's sidebar lists them inside one category: text-like first, then
    voice and stage, each by position and then ID."""
    return sorted(channels, key=lambda channel: (channel.kind not in TEXT_LIKE, channel.position, channel.id))


def sidebar(guild, bot_id, counts, outside=()):
    """The server's channel list as Discord's sidebar shows it, for the dashboard.

    counts maps a channel ID to {"searches": n, "hidden": n}. Every text and announcement channel
    is listed; other channels and threads only when they have something in counts. outside holds
    Lookups for channel IDs in counts that are not in the server's channel list, such as an
    archived thread (listed under its parent) or a deleted channel (listed as unknown).
    """
    channels = dict(guild.channels)
    unknown = []
    for channel_id, lookup in dict(outside).items():
        if lookup.channel is not None and lookup.guild is not None and lookup.guild.id == guild.id:
            channels[channel_id] = lookup.channel
        else:
            unknown.append({"id": str(channel_id), "deleted": lookup.deleted,
                            **counts.get(channel_id, {"searches": 0, "hidden": 0})})

    def entry(channel):
        found = counts.get(channel.id, {"searches": 0, "hidden": 0})
        return {"id": str(channel.id), "name": channel.name, "kind": channel.kind,
                "parent_id": str(channel.parent_id) if channel.parent_id else None,
                "archived": channel.archived, "locked": channel.locked, **found,
                "posting": posting(guild, channel, bot_id)}

    threads = {}
    for channel in channels.values():
        if channel.kind in THREADS and channel.id in counts:
            threads.setdefault(channel.parent_id, []).append(channel)
    listed = [channel for channel in channels.values()
              if channel.kind not in THREADS and channel.kind != "category"
              and (channel.kind in {"text", "announcement"} or channel.id in counts or channel.id in threads)]
    for parent_id in set(threads) - {channel.id for channel in listed}:
        # A thread whose parent is gone or unknown still gets listed, at the top of the server.
        for thread in threads.pop(parent_id):
            listed.append(thread)
    by_category = {}
    for channel in listed:
        parent = channels.get(channel.parent_id) if channel.kind not in THREADS else None
        by_category.setdefault(parent.id if parent is not None and parent.kind == "category" else None,
                               []).append(channel)
    categories = sorted((channels[key] for key in by_category if key is not None),
                        key=lambda category: (category.position, category.id))
    sections = []
    for category in [None, *categories]:
        members = by_category.get(category.id if category else None)
        if not members:
            continue
        rows = []
        for channel in discord_order(members):
            row = entry(channel)
            # Newest thread first.
            row["threads"] = [entry(thread) for thread in
                              sorted(threads.get(channel.id, []), key=lambda thread: thread.id, reverse=True)]
            rows.append(row)
        sections.append({"category": {"id": str(category.id), "name": category.name} if category else None,
                         "channels": rows})
    return {"source": guild.source, "sections": sections,
            "unknown": sorted(unknown, key=lambda channel: int(channel["id"]))}


def _overwrites(channel):
    return {int(key): Overwrite(overwrite.type == hikari.PermissionOverwriteType.ROLE,
                                P(overwrite.allow), P(overwrite.deny))
            for key, overwrite in (getattr(channel, "permission_overwrites", None) or {}).items()}


def _channel(channel, joined=None):
    kind = KINDS.get(channel.type, "other")
    metadata = getattr(channel, "metadata", None)
    if joined is None and kind == "private_thread":
        joined = getattr(channel, "member", None) is not None
    return Channel(int(channel.id), int(channel.guild_id), channel.name or "", kind,
                   int(getattr(channel, "position", 0) or 0),
                   int(channel.parent_id) if getattr(channel, "parent_id", None) else None,
                   _overwrites(channel), bool(metadata and metadata.is_archived),
                   bool(metadata and metadata.is_locked), joined)


def _icon(guild):
    icon = guild.make_icon_url(size=64)
    return str(icon) if icon else None


class ChannelDirectory:
    """Servers, channels and the bot's permissions, from the gateway cache or from REST.

    rest is None for a dashboard without a bot token; then nothing is known and `available` is False.
    Discord failures raise DiscordUnavailable, so callers can say Discord did not answer.
    """

    def __init__(self, rest=None, cache=None, *, timeout=TIMEOUT_SECONDS, ttl=TTL_SECONDS,
                 channel_ttl=CHANNEL_TTL_SECONDS):
        self.rest, self.cache = rest, cache
        self.timeout, self.ttl, self.channel_ttl = timeout, ttl, channel_ttl
        # Server ID to (time it is forgotten, Guild or None when the bot is not in it).
        self._guilds = {}
        # Channel ID to (time it is forgotten, server ID or None, deleted).
        self._channels = {}
        self._fetching = {}
        self._bot = None

    @property
    def available(self):
        return self.rest is not None or self.cache is not None

    async def _ask(self, call):
        try:
            async with asyncio.timeout(self.timeout):
                return await call
        except (hikari.NotFoundError, hikari.ForbiddenError):
            # Answers, not failures: the caller decides what a missing or hidden thing means.
            raise
        except UNAVAILABLE as error:
            raise DiscordUnavailable(f"Discord did not answer: {describe(error)}") from error

    async def bot(self):
        """The bot's ID, name and avatar, or None without a way to ask Discord."""
        me = self.cache.get_me() if self.cache is not None else None
        if me is None and self._bot is None and self.rest is not None:
            me = await self._ask(self.rest.fetch_my_user())
        if me is not None:
            self._bot = {"id": str(me.id), "name": me.global_name or me.username,
                         "avatar_url": str(me.display_avatar_url)}
        return self._bot

    async def bot_id(self):
        bot = await self.bot()
        return int(bot["id"]) if bot else None

    async def servers(self):
        """The servers the bot is in, as {id, name, icon_url}. Used for sign-in with the access key."""
        if self.cache is not None and self.cache.get_available_guilds_view():
            guilds = list(self.cache.get_available_guilds_view().values())
            if not self.cache.get_unavailable_guilds_view():
                return [{"id": str(guild.id), "name": guild.name, "icon_url": _icon(guild)} for guild in guilds]
        if self.rest is None:
            return []

        async def fetch():
            return [guild async for guild in self.rest.fetch_my_guilds()]
        return [{"id": str(guild.id), "name": guild.name, "icon_url": _icon(guild)}
                for guild in await self._ask(fetch())]

    def _cached(self, guild_id):
        if self.cache is None:
            return None
        guild = self.cache.get_available_guild(guild_id)
        roles = self.cache.get_roles_view_for_guild(guild_id)
        me = self.cache.get_me()
        member = self.cache.get_member(guild_id, me.id) if me is not None else None
        # Every server has an @everyone role; without it the cache has not received the server yet.
        if guild is None or guild_id not in roles or member is None:
            return None
        channels = {int(channel.id): _channel(channel)
                    for channel in self.cache.get_guild_channels_view_for_guild(guild_id).values()}
        channels.update({int(thread.id): _channel(thread)
                         for thread in self.cache.get_threads_view_for_guild(guild_id).values()})
        return Guild(int(guild_id), guild.name, _icon(guild), int(guild.owner_id),
                     {int(role_id): role.permissions for role_id, role in roles.items()}, channels,
                     tuple(int(role) for role in member.role_ids),
                     member.communication_disabled_until() is not None, "gateway")

    async def _fetched(self, guild_id):
        bot_id = await self.bot_id()
        try:
            guild = await self._ask(self.rest.fetch_guild(guild_id))
        except (hikari.NotFoundError, hikari.ForbiddenError):
            # The bot is not in the server, or has just left it.
            return None
        found = await self._ask(self.rest.fetch_guild_channels(guild_id))
        active = await self._ask(self.rest.fetch_active_threads(guild_id))
        member = await self._ask(self.rest.fetch_member(guild_id, bot_id))
        channels = {int(channel.id): _channel(channel) for channel in found}
        channels.update({int(thread.id): _channel(thread) for thread in active})
        return Guild(int(guild_id), guild.name, _icon(guild), int(guild.owner_id),
                     {int(role_id): role.permissions for role_id, role in guild.roles.items()}, channels,
                     tuple(int(role) for role in member.role_ids),
                     member.communication_disabled_until() is not None, "rest")

    async def guild(self, guild_id):
        """The server with its channels, or None when the bot is not in it or nothing is known."""
        guild_id = int(guild_id)
        cached = self._cached(guild_id)
        if cached is not None:
            return cached
        if self.rest is None:
            return None
        now = time.monotonic()
        kept = self._guilds.get(guild_id)
        if kept is not None and kept[0] > now:
            return kept[1]
        # Requests that arrive while one fetch runs wait for it instead of asking Discord again.
        task = self._fetching.get(guild_id)
        if task is None:
            task = self._fetching[guild_id] = asyncio.create_task(self._fetched(guild_id))

            def done(task):
                self._fetching.pop(guild_id, None)
                # Every waiter gets the error; this keeps asyncio quiet when all of them went away.
                if not task.cancelled():
                    task.exception()
            task.add_done_callback(done)
        result = await asyncio.shield(task)
        self._guilds[guild_id] = (time.monotonic() + self.ttl, result)
        return result

    async def find(self, channel_id):
        """Look up one channel or thread by ID, in whichever server it is."""
        channel_id = int(channel_id)
        if self.cache is not None:
            cached = self.cache.get_guild_channel(channel_id) or self.cache.get_thread(channel_id)
            if cached is not None:
                guild = await self.guild(cached.guild_id)
                if guild is not None:
                    return Lookup(guild, guild.channels.get(channel_id) or _channel(cached))
        for _, guild in self._guilds.values():
            if guild is not None and channel_id in guild.channels:
                fresh = await self.guild(guild.id)
                if fresh is not None and channel_id in fresh.channels:
                    return Lookup(fresh, fresh.channels[channel_id])
        if self.rest is None:
            return Lookup()
        now = time.monotonic()
        kept = self._channels.get(channel_id)
        if kept is None or kept[0] <= now:
            try:
                fetched = await self._ask(self.rest.fetch_channel(channel_id))
            except hikari.NotFoundError:
                kept = (now + self.channel_ttl, None, True, None)
            except hikari.ForbiddenError:
                kept = (now + self.channel_ttl, None, False, None)
            else:
                guild_id = getattr(fetched, "guild_id", None)
                kept = (now + self.channel_ttl, int(guild_id) if guild_id else None, False,
                        _channel(fetched) if guild_id else None)
            self._channels[channel_id] = kept
        _, guild_id, deleted, channel = kept
        if guild_id is None:
            return Lookup(deleted=deleted)
        guild = await self.guild(guild_id)
        if guild is None:
            return Lookup()
        return Lookup(guild, guild.channels.get(channel_id) or channel)

    async def names(self, channel_ids, guild_ids=()):
        """Channel ID to its name, from the cache or the listed servers. Never asks per channel.

        A server Discord does not answer for is skipped: names are a convenience.
        """
        for guild_id in set(guild_ids):
            if self._cached(int(guild_id)) is None and self.rest is not None:
                try:
                    await self.guild(guild_id)
                except DiscordUnavailable:
                    pass
        names = {}
        for channel_id in channel_ids:
            cached = None
            if self.cache is not None:
                cached = self.cache.get_guild_channel(int(channel_id)) or self.cache.get_thread(int(channel_id))
            if cached is not None and cached.name:
                names[channel_id] = cached.name
                continue
            for _, guild in self._guilds.values():
                if guild is not None and int(channel_id) in guild.channels:
                    names[channel_id] = guild.channels[int(channel_id)].name
                    break
        return names
