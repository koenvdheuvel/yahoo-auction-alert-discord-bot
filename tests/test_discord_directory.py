"""Channel lists in Discord's order and the bot's permissions per channel, from the cache or from REST."""
from types import SimpleNamespace
import unittest

import hikari

from dashboard_auth import DiscordUnavailable
from devtools.fake_discord import BOT_ID, PERMISSIONS, FakeDiscord
from discord_directory import (POST, ChannelDirectory, Channel, Guild, Lookup, Overwrite, channel_permissions,
                               member_permissions, posting, sidebar)

P = hikari.Permissions
GUILD = 10
EVERYONE_VIEW = P.VIEW_CHANNEL
ROLE, OTHER_ROLE, MEMBER = 20, 21, 30


def guild(channels=(), roles=None, bot_roles=(ROLE,), owner_id=1, timed_out=False):
    return Guild(GUILD, "Poster hunters", None, owner_id, roles or {GUILD: EVERYONE_VIEW, ROLE: POST},
                 {channel.id: channel for channel in channels}, tuple(bot_roles), timed_out, "rest")


def channel(channel_id, kind="text", parent_id=None, position=0, overwrites=None, **flags):
    return Channel(channel_id, GUILD, f"channel-{channel_id}", kind, position, parent_id, overwrites or {}, **flags)


class ChannelPermissionTests(unittest.TestCase):
    def test_overwrites_apply_in_discords_order(self):
        base = P.VIEW_CHANNEL | P.SEND_MESSAGES
        # @everyone loses Send Messages, a role gets it back, the member's own overwrite takes it away.
        overwrites = {GUILD: Overwrite(True, deny=P.SEND_MESSAGES), ROLE: Overwrite(True, allow=P.SEND_MESSAGES),
                      MEMBER: Overwrite(False, deny=P.SEND_MESSAGES)}
        self.assertTrue(channel_permissions(base, GUILD, 99, [ROLE], overwrites) & P.SEND_MESSAGES)
        self.assertFalse(channel_permissions(base, GUILD, MEMBER, [ROLE], overwrites) & P.SEND_MESSAGES)
        self.assertFalse(channel_permissions(base, GUILD, 99, [], overwrites) & P.SEND_MESSAGES)

    def test_a_role_allow_beats_another_roles_deny(self):
        overwrites = {ROLE: Overwrite(True, allow=P.EMBED_LINKS), OTHER_ROLE: Overwrite(True, deny=P.EMBED_LINKS)}
        self.assertTrue(channel_permissions(P.VIEW_CHANNEL, GUILD, 99, [ROLE, OTHER_ROLE], overwrites) & P.EMBED_LINKS)

    def test_the_everyone_overwrite_is_not_applied_again_as_a_role(self):
        # Member role lists can include @everyone. A role deny must still win over the @everyone allow.
        overwrites = {GUILD: Overwrite(True, allow=P.ADD_REACTIONS), ROLE: Overwrite(True, deny=P.ADD_REACTIONS)}
        self.assertFalse(channel_permissions(P.VIEW_CHANNEL, GUILD, 99, [GUILD, ROLE], overwrites) & P.ADD_REACTIONS)

    def test_a_member_overwrite_needs_the_member_type(self):
        # A role overwrite that happens to share the member's ID is not the member's own.
        overwrites = {MEMBER: Overwrite(True, deny=P.SEND_MESSAGES)}
        self.assertTrue(channel_permissions(P.VIEW_CHANNEL | P.SEND_MESSAGES, GUILD, MEMBER, [], overwrites)
                        & P.SEND_MESSAGES)

    def test_without_view_channel_nothing_counts_and_administrators_keep_everything(self):
        overwrites = {GUILD: Overwrite(True, deny=P.VIEW_CHANNEL)}
        self.assertEqual(channel_permissions(P.VIEW_CHANNEL | P.SEND_MESSAGES, GUILD, 99, [], overwrites), P.NONE)
        self.assertEqual(channel_permissions(P.ADMINISTRATOR, GUILD, 99, [], overwrites), P.all_permissions())

    def test_threads_use_their_parents_overwrites(self):
        parent = channel(1, overwrites={ROLE: Overwrite(True, deny=P.SEND_MESSAGES_IN_THREADS)})
        thread = channel(2, "thread", parent_id=1)
        server = guild([parent, thread], roles={GUILD: EVERYONE_VIEW, ROLE: POST | P.SEND_MESSAGES_IN_THREADS})
        self.assertTrue(member_permissions(server, parent, BOT_ID, [ROLE]) & P.SEND_MESSAGES)
        self.assertFalse(member_permissions(server, thread, BOT_ID, [ROLE]) & P.SEND_MESSAGES_IN_THREADS)

    def test_the_owner_and_a_member_in_timeout(self):
        text = channel(1, overwrites={GUILD: Overwrite(True, deny=P.SEND_MESSAGES)})
        server = guild([text], owner_id=BOT_ID)
        self.assertEqual(member_permissions(server, text, BOT_ID, []), P.all_permissions())
        self.assertEqual(member_permissions(server, text, BOT_ID, [], timed_out=True), P.all_permissions())
        # The timeout applies after the overwrites: a channel that allows more does not undo it.
        generous = channel(2, overwrites={ROLE: Overwrite(True, allow=P.SEND_MESSAGES | P.MANAGE_CHANNELS)})
        server = guild([text, generous], roles={GUILD: EVERYONE_VIEW, ROLE: POST})
        self.assertEqual(member_permissions(server, generous, BOT_ID, [ROLE], timed_out=True),
                         P.VIEW_CHANNEL | P.READ_MESSAGE_HISTORY)

    def test_a_thread_without_a_known_parent_gets_nothing(self):
        orphan = channel(5, "thread", parent_id=404)
        server = guild([orphan], roles={GUILD: EVERYONE_VIEW | P.MANAGE_CHANNELS, ROLE: POST})
        self.assertEqual(member_permissions(server, orphan, BOT_ID, [ROLE]), P.NONE)


class PostingTests(unittest.TestCase):
    def test_a_channel_with_every_permission_can_take_searches(self):
        result = posting(guild([channel(1)]), channel(1), BOT_ID)
        self.assertEqual((result["can_post"], result["missing"], result["bulk_delete"]), (True, [], False))

    def test_it_names_what_is_missing(self):
        denied = channel(1, overwrites={ROLE: Overwrite(True, deny=P.ADD_REACTIONS | P.READ_MESSAGE_HISTORY)})
        result = posting(guild([denied]), denied, BOT_ID)
        self.assertEqual((result["can_post"], result["missing"]), (False, ["Add Reactions", "Read Message History"]))
        # Without Send Messages, Discord also drops Embed Links; only the cause is named.
        silenced = channel(2, overwrites={ROLE: Overwrite(True, deny=P.SEND_MESSAGES)})
        self.assertEqual(posting(guild([silenced]), silenced, BOT_ID)["missing"], ["Send Messages"])
        hidden = channel(3, overwrites={GUILD: Overwrite(True, deny=P.VIEW_CHANNEL)})
        self.assertEqual(posting(guild([hidden], roles={GUILD: EVERYONE_VIEW, ROLE: POST & ~P.VIEW_CHANNEL}),
                                 hidden, BOT_ID)["missing"], ["View Channel"])

    def test_threads_need_send_messages_in_threads_and_must_be_open_to_the_bot(self):
        parent = channel(1)
        thread = channel(2, "thread", parent_id=1)
        self.assertEqual(posting(guild([parent, thread]), thread, BOT_ID)["missing"], ["Send Messages in Threads"])
        roles = {GUILD: EVERYONE_VIEW, ROLE: POST | P.SEND_MESSAGES_IN_THREADS}
        self.assertTrue(posting(guild([parent, thread], roles=roles), thread, BOT_ID)["can_post"])
        locked = channel(3, "thread", parent_id=1, locked=True)
        self.assertEqual(posting(guild([parent, locked], roles=roles), locked, BOT_ID)["problems"], ["The thread is locked."])
        private = channel(4, "private_thread", parent_id=1, joined=False)
        self.assertFalse(posting(guild([parent, private], roles=roles), private, BOT_ID)["can_post"])
        roles[ROLE] |= P.MANAGE_THREADS
        self.assertTrue(posting(guild([parent, private], roles=roles), private, BOT_ID)["can_post"])

    def test_forums_voice_and_categories_cannot_take_searches(self):
        for kind in ("forum", "voice", "category"):
            result = posting(guild([channel(1, kind)]), channel(1, kind), BOT_ID)
            self.assertFalse(result["can_post"], kind)
            self.assertEqual(result["missing"], [], kind)


class SidebarTests(unittest.TestCase):
    def test_channels_are_grouped_and_ordered_like_discord(self):
        channels = [
            channel(100, "category", position=1), channel(200, "category", position=0),
            channel(1, parent_id=100, position=2), channel(2, "voice", parent_id=100, position=0),
            channel(3, "announcement", parent_id=100, position=5), channel(4, position=9),
            channel(5, parent_id=200, position=0), channel(6, "voice", parent_id=200, position=1),
            channel(7, "thread", parent_id=1), channel(8, "thread", parent_id=1), channel(9, "thread", parent_id=1),
            channel(10, "forum", parent_id=200, position=3), channel(300, "category", position=2),
        ]
        counts = {2: {"searches": 1, "hidden": 0}, 7: {"searches": 1, "hidden": 0}, 9: {"searches": 0, "hidden": 2}}
        result = sidebar(guild(channels), BOT_ID, counts)
        layout = [(section["category"] and section["category"]["name"],
                   [(row["name"], [thread["name"] for thread in row["threads"]]) for row in section["channels"]])
                  for section in result["sections"]]
        # Channels without a category first, then categories by position; text before voice in each;
        # voice and forum channels only when they have searches or hidden listings; a text channel's
        # active threads, newest first; an empty category is left out.
        self.assertEqual(layout, [
            (None, [("channel-4", [])]),
            ("channel-200", [("channel-5", [])]),
            ("channel-100", [("channel-1", ["channel-9", "channel-8", "channel-7"]), ("channel-3", []),
                             ("channel-2", [])]),
        ])
        self.assertEqual(result["unknown"], [])

    def test_archived_threads_join_their_parent_and_deleted_channels_are_unknown(self):
        server = guild([channel(1)])
        archived = channel(5, "thread", parent_id=1, archived=True)
        counts = {5: {"searches": 1, "hidden": 0}, 6: {"searches": 2, "hidden": 0}, 7: {"searches": 0, "hidden": 1}}
        result = sidebar(server, BOT_ID, counts, {5: Lookup(server, archived), 6: Lookup(deleted=True), 7: Lookup()})
        row = result["sections"][0]["channels"][0]
        self.assertEqual([(thread["id"], thread["archived"]) for thread in row["threads"]], [("5", True)])
        self.assertEqual(result["unknown"], [{"id": "6", "deleted": True, "searches": 2, "hidden": 0},
                                             {"id": "7", "deleted": False, "searches": 0, "hidden": 1}])


class FakeCache:
    """The parts of hikari's gateway cache the directory reads, for one server."""

    def __init__(self, server, channels, threads, me=True):
        self.server, self.channels, self.threads = server, channels, threads
        self.me = SimpleNamespace(id=hikari.Snowflake(BOT_ID), username="PosterFinder", global_name=None,
                                  display_avatar_url="https://cdn.example/bot.png") if me else None

    def get_me(self):
        return self.me

    def get_available_guild(self, guild_id):
        return self.server if self.server and guild_id == GUILD else None

    def get_available_guilds_view(self):
        return {GUILD: self.server} if self.server else {}

    def get_unavailable_guilds_view(self):
        return {}

    def get_roles_view_for_guild(self, guild_id):
        if not self.server or guild_id != GUILD:
            return {}
        return {GUILD: SimpleNamespace(permissions=EVERYONE_VIEW), ROLE: SimpleNamespace(permissions=POST)}

    def get_member(self, guild_id, user_id):
        if not self.server or guild_id != GUILD:
            return None
        return SimpleNamespace(role_ids=[hikari.Snowflake(ROLE)], communication_disabled_until=lambda: None)

    def get_guild_channels_view_for_guild(self, guild_id):
        return self.channels if self.server else {}

    def get_threads_view_for_guild(self, guild_id):
        return self.threads if self.server else {}

    def get_guild_channel(self, channel_id):
        return self.channels.get(channel_id) if self.server else None

    def get_thread(self, channel_id):
        return self.threads.get(channel_id) if self.server else None


def cached_channel(channel_id, name, kind=hikari.ChannelType.GUILD_TEXT, parent_id=None, overwrites=()):
    return SimpleNamespace(
        id=hikari.Snowflake(channel_id), guild_id=hikari.Snowflake(GUILD), name=name, type=kind, position=0,
        parent_id=parent_id, permission_overwrites={
            hikari.Snowflake(target): hikari.PermissionOverwrite(id=target, type=kind_, allow=allow, deny=deny)
            for target, kind_, allow, deny in overwrites})


class DirectoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeDiscord(client_secret="fake-client-secret-0123456789", bot_token="bot-token")
        self.fake.add_guild(GUILD, "Poster hunters", owner_id=1)
        self.fake.add_channel(GUILD, 100, "POSTERS", "category")
        self.fake.add_channel(GUILD, 101, "posters-yahoo", parent_id=100)
        self.fake.add_channel(GUILD, 102, "staff", parent_id=100, overwrites=[(GUILD + 9, "role", 0,
                                                                                PERMISSIONS["add_reactions"])])
        self.fake.add_channel(GUILD, 103, "sold-out", "thread", parent_id=101)
        self.fake.add_channel(GUILD, 104, "last-year", "thread", parent_id=101, archived=True)
        await self.fake.start()
        self.app = hikari.RESTApp(url=self.fake.api_url, max_retries=0)
        await self.app.start()
        self.rest = self.app.acquire("bot-token", hikari.TokenType.BOT)
        self.rest.start()

    async def asyncTearDown(self):
        await self.rest.close()
        await self.app.close()
        await self.fake.close()

    def guild_calls(self):
        return [path for _, path in self.fake.calls if path.startswith("/api/v10/guilds/")]

    async def test_rest_gives_channels_threads_and_the_bots_roles(self):
        directory = ChannelDirectory(self.rest)
        server = await directory.guild(GUILD)
        self.assertEqual(server.source, "rest")
        self.assertEqual({key: value.kind for key, value in server.channels.items()},
                         {100: "category", 101: "text", 102: "text", 103: "thread"})
        self.assertEqual(posting(server, server.channels[102], BOT_ID)["missing"], ["Add Reactions"])
        self.assertTrue(posting(server, server.channels[101], BOT_ID)["can_post"])
        self.assertEqual((await directory.bot())["name"], "PosterFinderDev")
        # A second request within the minute asks Discord nothing.
        calls = len(self.guild_calls())
        await directory.guild(GUILD)
        self.assertEqual(len(self.guild_calls()), calls)

    async def test_lookups_tell_an_archived_thread_from_a_deleted_channel(self):
        directory = ChannelDirectory(self.rest)
        found = await directory.find(104)
        self.assertEqual((found.guild.id, found.channel.kind, found.channel.archived), (GUILD, "thread", True))
        self.assertEqual(await directory.find(999), Lookup(deleted=True))
        self.assertIsNone(await directory.guild(4040))
        # The answer for a deleted channel is kept, so a page reload does not ask again.
        calls = len(self.fake.calls)
        await directory.find(999)
        self.assertEqual(len(self.fake.calls), calls)

    async def test_discord_being_down_is_not_a_missing_channel(self):
        directory = ChannelDirectory(self.rest)
        self.fake.down = True
        with self.assertRaises(DiscordUnavailable):
            await directory.guild(GUILD)
        with self.assertRaises(DiscordUnavailable):
            await directory.find(999)

    async def test_the_gateway_cache_answers_without_rest(self):
        overwrite = (ROLE, hikari.PermissionOverwriteType.ROLE, P.NONE, P.EMBED_LINKS)
        channels = {101: cached_channel(101, "posters-yahoo"), 102: cached_channel(102, "staff", overwrites=[overwrite])}
        cache = FakeCache(SimpleNamespace(name="Poster hunters", owner_id=1, make_icon_url=lambda size: None),
                          channels, {})
        directory = ChannelDirectory(self.rest, cache)
        server = await directory.guild(GUILD)
        self.assertEqual((server.source, sorted(server.channels)), ("gateway", [101, 102]))
        self.assertEqual(posting(server, server.channels[102], BOT_ID)["missing"], ["Embed Links"])
        self.assertEqual((await directory.find(101)).channel.name, "posters-yahoo")
        self.assertEqual(await directory.names({101, 103}), {101: "posters-yahoo"})
        self.assertEqual(self.guild_calls(), [])

    async def test_a_server_the_cache_has_not_received_yet_comes_from_rest(self):
        # Right after connecting, the cache knows the bot but not the server's channels.
        directory = ChannelDirectory(self.rest, FakeCache(None, {}, {}))
        server = await directory.guild(GUILD)
        self.assertEqual((server.source, server.channels[101].name), ("rest", "posters-yahoo"))
        self.assertEqual((await directory.find(103)).channel.name, "sold-out")

    async def test_without_a_token_nothing_is_known(self):
        directory = ChannelDirectory()
        self.assertFalse(directory.available)
        self.assertIsNone(await directory.guild(GUILD))
        self.assertEqual(await directory.find(101), Lookup())
        self.assertIsNone(await directory.bot())
