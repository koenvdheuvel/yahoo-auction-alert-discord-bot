"""Managing servers from the dashboard: searches, hidden listings, cleanup, notifications and status.

Discord is the local fake, reached over REST as the standalone dashboard does. Sessions are opened
directly; signing in is tested in test_dashboard_auth.py.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
import hikari

from channel_maintenance import MAX_DELETE_COUNT
from commands.base import SEARCH_QUERY_MAX_LENGTH, clean_search_query
from commands.register import RegisterCommand
from config import Settings
from dashboard import COOKIE, DashboardServer, Session
from dashboard_auth import DiscordGuilds, Member
from devtools.fake_discord import BOT_ID, PERMISSIONS, FakeDiscord
from discord_directory import ChannelDirectory
from models import DeliveryJob, Item, Message, configure_database, create_tables, database
from observability import JsonFormatter, Metrics
from repositories import Repository

SECRET = "fake-client-secret-0123456789abcdef"
BOT_TOKEN = "fake-bot-token"
GUILD_A, GUILD_B = 1100000000000000001, 1100000000000000002
MANAGER, ADMIN = 1200000000000000001, 1200000000000000002
# Long IDs, so a test can tell that one is missing from an answer.
ALICE, BOB, DAVE, ERIN = 1300000000000000001, 1300000000000000002, 1300000000000000004, 1300000000000000005
CATEGORY, POSTERS, STAFF, QUIET, VOICE, THREAD, OLD_THREAD, SHARED, GONE = 40, 41, 42, 43, 44, 45, 46, 47, 49
VINYL = 51
INDEX = '<!doctype html><html><head><title>Dashboard</title></head><body><div id="root"></div></body></html>'


def snowflake(moment):
    """A Discord message ID created at `moment`."""
    return (int(moment.timestamp() * 1000) - 1420070400000) << 22


def fake_discord():
    fake = FakeDiscord(client_secret=SECRET, bot_token=BOT_TOKEN)
    for user_id, name in ((ALICE, "alice"), (BOB, "bob"), (DAVE, "dave"), (ERIN, "erin")):
        fake.add_user(user_id, name, name.title())
    first = fake.add_guild(GUILD_A, "Poster hunters", owner_id=DAVE)
    first.roles.update({MANAGER: PERMISSIONS["manage_channels"], ADMIN: PERMISSIONS["administrator"]})
    first.members.update({ALICE: [MANAGER], BOB: [], DAVE: [], ERIN: [ADMIN]})
    bot_role = GUILD_A + 9
    deny_manage = [(MANAGER, "role", 0, PERMISSIONS["manage_channels"])]
    fake.add_channel(GUILD_A, CATEGORY, "POSTERS", "category")
    fake.add_channel(GUILD_A, POSTERS, "posters", parent_id=CATEGORY, position=0)
    fake.add_channel(GUILD_A, STAFF, "staff", parent_id=CATEGORY, position=1, overwrites=deny_manage)
    fake.add_channel(GUILD_A, QUIET, "quiet", parent_id=CATEGORY, position=2,
                     overwrites=[(bot_role, "role", 0, PERMISSIONS["add_reactions"])])
    fake.add_channel(GUILD_A, VOICE, "lounge", "voice", parent_id=CATEGORY)
    fake.add_channel(GUILD_A, THREAD, "sold-out", "thread", parent_id=POSTERS)
    fake.add_channel(GUILD_A, OLD_THREAD, "last-year", "thread", parent_id=POSTERS, archived=True)
    # The role may not manage here, but Alice's own overwrite lets her.
    fake.add_channel(GUILD_A, SHARED, "shared", parent_id=CATEGORY, position=3,
                     overwrites=[*deny_manage, (ALICE, "member", PERMISSIONS["manage_channels"], 0)])
    second = fake.add_guild(GUILD_B, "Record shop", owner_id=ERIN)
    second.members.update({ERIN: []})
    fake.add_channel(GUILD_B, VINYL, "vinyl")
    return fake


class History:
    """What hikari's fetch_messages returns: something to limit and iterate."""

    def __init__(self, messages):
        self.messages = list(messages)

    def limit(self, count):
        self.messages = self.messages[:count]
        return self

    async def __aiter__(self):
        for message in self.messages:
            yield message


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "alerts.db")
        configure_database(self.path)
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(POSTERS, "BABYMETAL poster", guild_id=GUILD_A)
        await self.repository.register_alert(VINYL, "Vinyl", guild_id=GUILD_B)
        # A search whose channel was deleted in Discord.
        await self.repository.register_alert(GONE, "Gone search", guild_id=GUILD_A)
        alerts = {alert["search_query"]: alert for alert in await self.repository.list_alerts()}
        self.alert_a, self.alert_b, self.gone = alerts["BABYMETAL poster"], alerts["Vinyl"], alerts["Gone search"]

        self.fake = fake_discord()
        await self.fake.start()
        self.rest_app = hikari.RESTApp(url=self.fake.api_url, max_retries=0)
        await self.rest_app.start()
        self.rest = self.rest_app.acquire(BOT_TOKEN, hikari.TokenType.BOT)
        self.rest.start()
        settings = replace(Settings(), token=BOT_TOKEN, database_path=self.path,
                           dashboard_public_url="http://127.0.0.1:1", dashboard_discord_client_secret=SECRET)
        assets = Path(self.directory.name) / "dist"
        assets.mkdir()
        (assets / "index.html").write_text(INDEX, encoding="utf-8")
        self.dashboard = DashboardServer(settings, self.repository, self.metrics, assets=assets,
                                         directory=ChannelDirectory(self.rest), guild_access=DiscordGuilds(self.rest))
        self.client = TestClient(TestServer(self.dashboard.application(), host="127.0.0.1"),
                                 cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.headers = {"Origin": str(self.client.make_url("/")).rstrip("/")}
        self.logs = []
        self.handler = logging.Handler()
        self.handler.emit = lambda record: self.logs.append(JsonFormatter().format(record))
        logging.getLogger("dashboard_manage").addHandler(self.handler)
        logging.getLogger("dashboard_manage").setLevel(logging.INFO)

    async def asyncTearDown(self):
        logging.getLogger("dashboard_manage").removeHandler(self.handler)
        await self.client.close()
        await self.dashboard.close()
        await self.rest.close()
        await self.rest_app.close()
        await self.fake.close()
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    def events(self, name):
        return [entry for entry in map(json.loads, self.logs) if entry["event"] == name]

    def sign_in(self, user_id, members=None, levels=None):
        """A Discord session, as signing in makes it. members maps server to the person's roles there,
        and levels to "manager" or "member"; a manager everywhere unless levels says otherwise."""
        members = members or {GUILD_A: Member((MANAGER,))}
        levels = {guild: "manager" for guild in members} | (levels or {})
        guilds = {guild: {"id": str(guild), "name": "server", "icon_url": None} for guild in members}
        user = {"id": str(user_id), "name": f"user {user_id}", "username": f"user{user_id}", "avatar_url": None}
        cookie = self.dashboard.open_session(Session(time.monotonic() + 3600, user=user, guilds=guilds, levels=levels,
                                                     members=members, checked=time.monotonic()))
        self.client.session.cookie_jar.update_cookies({COOKIE: cookie})

    async def call(self, method, path, **json_body):
        return await self.client.request(method, path, json=json_body if json_body else None, headers=self.headers)

    async def post(self, item_id, channel_id, alert_id, message_id):
        def create():
            Message.create(message_id=message_id, item=item_id, alert=alert_id, channel_id=channel_id)
        await self.repository._call("test_post", create)

    async def item(self, external_id, title="BABYMETAL poster", price=5000):
        return await self.repository._call("test_item", lambda: Item.create(
            item_id=external_id, checker="yahooauction", title=title, price=price, url="https://example.com").id)

    async def test_the_page_and_session_carry_the_bots_name(self):
        page = await (await self.client.get("/")).text()
        self.assertIn("<title>PosterFinderDev Dashboard</title>", page)
        session = await (await self.client.get("/api/session")).json()
        self.assertEqual((session["title"], session["bot"]["name"]), ("PosterFinderDev Dashboard", "PosterFinderDev"))
        self.sign_in(ALICE)
        session = await (await self.client.get("/api/session")).json()
        self.assertEqual(session["features"], {"notifications": True, "discord_data": True})

    async def test_the_channel_list_follows_discord_and_flags_what_is_wrong(self):
        self.sign_in(ALICE)
        await self.repository.register_alert(THREAD, "Thread search", guild_id=GUILD_A)
        await self.repository.register_alert(OLD_THREAD, "Archived search", guild_id=GUILD_A)
        body = await (await self.client.get(f"/api/guilds/{GUILD_A}/channels")).json()
        self.assertEqual(body["guild"]["name"], "Poster hunters")
        section = body["sections"][0]
        self.assertEqual(section["category"], {"id": str(CATEGORY), "name": "POSTERS"})
        rows = {row["name"]: row for row in section["channels"]}
        self.assertEqual(list(rows), ["posters", "staff", "quiet", "shared"])
        posters = rows["posters"]
        self.assertEqual((posters["searches"], posters["can_manage"], posters["posting"]["can_post"]), (1, True, True))
        self.assertEqual([(thread["name"], thread["archived"]) for thread in posters["threads"]],
                         [("last-year", True), ("sold-out", False)])
        self.assertEqual(rows["quiet"]["posting"]["missing"], ["Add Reactions"])
        self.assertFalse(rows["staff"]["can_manage"])
        self.assertTrue(rows["shared"]["can_manage"])
        self.assertEqual(body["unknown"], [{"id": str(GONE), "deleted": True, "searches": 1, "hidden": 0}])
        guilds = (await (await self.client.get("/api/guilds")).json())["guilds"]
        self.assertEqual([(guild["id"], guild["searches"]) for guild in guilds], [(str(GUILD_A), 4)])

    async def test_a_new_search_takes_its_server_from_discord_not_from_the_browser(self):
        self.sign_in(ALICE)
        response = await self.call("POST", "/api/alerts", channel_id=str(POSTERS), search_query="  vinyl  ",
                                   guild_id=str(GUILD_B))
        self.assertEqual(response.status, 201)
        alert = await response.json()
        self.assertEqual((alert["search_query"], alert["guild_id"], alert["channel_name"]),
                         ("vinyl", str(GUILD_A), "posters"))
        entry = self.events("alert_registered")[0]
        self.assertEqual((entry["actor_id"], entry["via"], entry["guild_id"]), (str(ALICE), "dashboard", GUILD_A))
        response = await self.call("POST", "/api/alerts", channel_id=str(POSTERS), search_query="vinyl")
        self.assertEqual(response.status, 409)
        self.assertIn("already exists in #posters", (await response.json())["message"])
        # A channel of another server and one that does not exist get the same answer.
        missing = [await (await self.call("POST", "/api/alerts", channel_id=str(channel), search_query="x")).json()
                   for channel in (VINYL, 999999)]
        self.assertEqual(missing, [{"error": "not_found", "message": "Channel not found"}] * 2)
        self.assertEqual([row["search_query"] for row in await self.repository.list_alerts(channel_id=VINYL)], ["Vinyl"])
        response = await self.call("POST", "/api/alerts", channel_id=str(THREAD), search_query="sold out")
        self.assertEqual(response.status, 201)

    async def test_the_bot_must_be_able_to_post_before_a_search_is_added(self):
        self.sign_in(ALICE)
        for channel, message in ((QUIET, "The bot needs Add Reactions there."),
                                 (VOICE, "Searches can only post in text channels"),
                                 (CATEGORY, "Searches can only post in text channels")):
            response = await self.call("POST", "/api/alerts", channel_id=str(channel), search_query="poster")
            self.assertEqual(response.status, 400, channel)
            self.assertIn(message, (await response.json())["message"])
        self.assertEqual(await self.repository.list_alerts(channel_id=QUIET), [])

    async def test_search_queries_follow_the_register_commands_rules(self):
        self.sign_in(ALICE)
        option = next(option for option in RegisterCommand._command_data.options.values()
                      if option.name == "search_query")
        self.assertEqual(option.max_length, SEARCH_QUERY_MAX_LENGTH)
        for query in ("   ", "x" * (SEARCH_QUERY_MAX_LENGTH + 1), "", 42):
            response = await self.call("POST", "/api/alerts", channel_id=str(POSTERS), search_query=query)
            self.assertEqual(response.status, 400, query)
            with self.assertRaises(ValueError) as error:
                clean_search_query(query)
            self.assertEqual((await response.json())["message"], str(error.exception))
        response = await self.call("POST", "/api/alerts", channel_id=str(POSTERS),
                                   search_query="x" * SEARCH_QUERY_MAX_LENGTH)
        self.assertEqual(response.status, 201)

    async def test_changes_need_manage_channels_in_the_channel_itself(self):
        item = await self.item("staff-item")
        await self.post(item, STAFF, None, 10)
        self.sign_in(ALICE)
        changes = (
            ("POST", "/api/alerts", {"channel_id": str(STAFF), "search_query": "staff"}),
            ("PUT", f"/api/channels/{STAFF}/hidden/{item}", {}),
            ("DELETE", f"/api/channels/{STAFF}/hidden/{item}", {}),
            ("POST", f"/api/channels/{STAFF}/posts/removal", {"message_ids": ["10"]}),
            ("POST", f"/api/channels/{STAFF}/history-scan", {"action": "add_reactions"}),
        )
        for method, path, body in changes:
            response = await self.call(method, path, **body)
            self.assertEqual(response.status, 403, path)
            self.assertIn("Manage Channels permission in #staff", (await response.json())["message"])
        # Reading is fine: the sign-in already needs Manage Channels in the server.
        self.assertEqual((await self.client.get(f"/api/channels/{STAFF}/hidden")).status, 200)
        # A member overwrite of her own beats the role's.
        response = await self.call("POST", "/api/alerts", channel_id=str(SHARED), search_query="shared")
        self.assertEqual(response.status, 201)
        # Administrators and the server owner are not held back by overwrites.
        for user_id, roles in ((ERIN, (ADMIN,)), (DAVE, ())):
            self.client.session.cookie_jar.clear()
            self.sign_in(user_id, {GUILD_A: Member(roles)})
            response = await self.call("POST", "/api/alerts", channel_id=str(STAFF), search_query=f"by {user_id}")
            self.assertEqual(response.status, 201, user_id)

    async def test_unregistering_says_what_it_touches_and_works_for_deleted_channels(self):
        item = await self.item("posted")
        await self.post(item, POSTERS, self.alert_a["id"], 20)
        self.sign_in(ALICE)
        detail = await (await self.client.get(f"/api/alerts/{self.alert_a['id']}")).json()
        self.assertEqual(detail["usage"], {"posts": 1, "waiting_posts": 0, "rule_versions": 0, "archived": 0,
                                           "legacy_filters": 0})
        self.assertEqual((detail["channel"]["name"], detail["channel"]["posting"]["can_post"]), ("posters", True))
        response = await self.call("DELETE", f"/api/alerts/{self.alert_a['id']}")
        self.assertEqual(response.status, 200)
        self.assertEqual(await self.repository.list_alerts(channel_id=POSTERS), [])
        self.assertEqual(self.events("alert_unregistered")[0]["actor_id"], str(ALICE))
        # The post stays in Discord and in the table, without its search.
        rows = await self.repository._call("test_rows", lambda: list(Message.select().dicts()))
        self.assertEqual([(row["message_id"], row["alert"], row["deleted"]) for row in rows], [(20, None, False)])
        detail = await (await self.client.get(f"/api/alerts/{self.gone['id']}")).json()
        self.assertEqual((detail["channel"], detail["channel_deleted"]), (None, True))
        self.assertEqual((await self.call("DELETE", f"/api/alerts/{self.gone['id']}")).status, 200)
        # When Discord does not answer, a change waits instead of guessing.
        await self.repository.register_alert(STAFF, "later", guild_id=GUILD_A)
        later = (await self.repository.list_alerts(channel_id=STAFF))[0]
        self.fake.down = True
        self.dashboard.directory = ChannelDirectory(self.rest)
        response = await self.call("DELETE", f"/api/alerts/{later['id']}")
        self.assertEqual((response.status, (await response.json())["error"]), (503, "discord_unavailable"))

    async def test_legacy_filters_are_deleted_like_filters_delete(self):
        filter_id = await self.repository.add_filter(POSTERS, "BABYMETAL poster", "text", "blacklist", "メモリアル")
        self.sign_in(ALICE)
        rules = await (await self.client.get(f"/api/alerts/{self.alert_a['id']}/rules")).json()
        self.assertEqual([row["value"] for row in rules["legacy_filters"]], ["メモリアル"])
        path = f"/api/alerts/{self.alert_a['id']}/legacy-filters/{filter_id}"
        self.assertEqual((await self.call("DELETE", path)).status, 200)
        self.assertEqual(await self.repository.list_filters(POSTERS), [])
        self.assertEqual((await self.call("DELETE", path)).status, 404)
        self.assertEqual(self.events("filter_deleted")[0]["filter_id"], filter_id)

    async def test_hiding_works_like_the_trash_reaction(self):
        item, other = await self.item("hide-me"), await self.item("never-here")
        await self.post(item, POSTERS, self.alert_a["id"], 30)
        await self.post(item, POSTERS, self.alert_a["id"], 31)
        await self.repository.subscribe(item, BOB)
        self.sign_in(ALICE)
        posts = (await (await self.client.get(f"/api/channels/{POSTERS}/posts")).json())["posts"]
        self.assertEqual([(post["message_id"], post["subscribers"], post["subscribed_by_me"], post["hidden"])
                          for post in posts], [("31", 1, False, False), ("30", 1, False, False)])
        # Who subscribed is never in the answer.
        self.assertNotIn(str(BOB), json.dumps(posts))
        response = await self.call("PUT", f"/api/channels/{POSTERS}/hidden/{item}")
        self.assertEqual((await response.json())["posts_queued"], 2)
        self.assertEqual(self.events("item_blacklisted")[0]["actor_id"], str(ALICE))
        # The posts go even though Bob follows the listing, as with 🗑️; his DMs keep coming.
        jobs = await self.repository.due_deliveries()
        self.assertEqual(sorted(job["message_id"] for job in jobs), [30, 31])
        self.assertIsNotNone(await self.repository.begin_delivery(jobs[0]["id"]))
        self.assertEqual(len(await self.repository.subscriptions(BOB)), 1)
        hidden = await (await self.client.get(f"/api/channels/{POSTERS}/hidden")).json()
        self.assertEqual([row["external_id"] for row in hidden["items"]], ["hide-me"])
        self.assertEqual((await self.call("PUT", f"/api/channels/{POSTERS}/hidden/{other}")).status, 404)
        self.assertEqual((await self.call("DELETE", f"/api/channels/{POSTERS}/hidden/{item}")).status, 200)
        self.assertEqual((await self.repository.hidden_items(POSTERS))["total"], 0)
        self.assertEqual((await self.call("DELETE", f"/api/channels/{POSTERS}/hidden/{item}")).status, 404)

    async def test_cleanup_queues_the_channels_posts_and_keeps_followed_ones(self):
        now = datetime.now(timezone.utc)
        followed, recent, older, ancient = [await self.item(name) for name in ("followed", "recent", "older", "ancient")]
        ids = {"followed": snowflake(now - timedelta(hours=1)), "recent": snowflake(now - timedelta(hours=2)),
               "older": snowflake(now - timedelta(days=3)), "ancient": snowflake(now - timedelta(days=100))}
        await self.post(followed, POSTERS, self.alert_a["id"], ids["followed"])
        await self.post(recent, POSTERS, self.alert_a["id"], ids["recent"])
        await self.post(older, POSTERS, None, ids["older"])
        await self.post(ancient, POSTERS, self.alert_a["id"], ids["ancient"])
        await self.repository.subscribe(followed, BOB)
        self.sign_in(ALICE)
        preview = await (await self.call("POST", f"/api/channels/{POSTERS}/posts/removal-preview", days=30)).json()
        self.assertEqual([post["message_id"] for post in preview["posts"]], [str(ids["recent"]), str(ids["older"])])
        self.assertEqual((preview["posts_in_range"], preview["kept"]), (3, {"subscribed": 1, "queued": 0}))
        narrowed = await (await self.call("POST", f"/api/channels/{POSTERS}/posts/removal-preview", days=None,
                                          alert_id=self.alert_a["id"])).json()
        self.assertEqual([post["message_id"] for post in narrowed["posts"]], [str(ids["recent"]), str(ids["ancient"])])
        self.assertEqual((await self.call("POST", f"/api/channels/{POSTERS}/posts/removal-preview", days=12)).status,
                         400)
        response = await self.call("POST", f"/api/channels/{POSTERS}/posts/removal",
                                   message_ids=[str(ids[name]) for name in ("followed", "recent", "older")])
        self.assertEqual(await response.json(), {"queued": 2, "skipped": 1, "bot_running": False})
        status = await (await self.client.get(f"/api/channels/{POSTERS}/posts/removal")).json()
        self.assertEqual((status["run"]["total"], status["run"]["pending"]), (2, 2))
        jobs = await self.repository._call("test_jobs", lambda: list(DeliveryJob.select().dicts()))
        self.assertEqual({(job["payload"], job["alert"]) for job in jobs}, {('{"reason": "cleanup"}', None)})
        self.assertEqual(self.events("post_removal_queued")[0]["queued"], 2)
        # A search's own removal runs do not count this channel cleanup as theirs.
        self.assertIsNone((await self.repository.post_removal_status(self.alert_a["id"]))["run"])

    async def test_history_scans_need_the_running_bot_and_report_progress(self):
        self.sign_in(ALICE)
        response = await self.call("POST", f"/api/channels/{POSTERS}/history-scan", action="delete_bot_posts", count=5)
        self.assertEqual(response.status, 409)
        self.assertIn("needs the bot running", (await response.json())["message"])
        message = SimpleNamespace(id=61, author=SimpleNamespace(id=BOT_ID), type=hikari.MessageType.DEFAULT,
                                  interaction_metadata=None)
        rest = SimpleNamespace(fetch_messages=Mock(return_value=History([message])), delete_message=AsyncMock())
        self.dashboard.management.bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=BOT_ID))
        for count in (0, MAX_DELETE_COUNT + 1, True):
            response = await self.call("POST", f"/api/channels/{POSTERS}/history-scan", action="delete_bot_posts",
                                       count=count)
            self.assertEqual(response.status, 400, count)
        response = await self.call("POST", f"/api/channels/{POSTERS}/history-scan", action="delete_bot_posts", count=5)
        self.assertEqual(response.status, 202)
        await asyncio.gather(*self.dashboard.management.scan_tasks)
        scan = (await (await self.client.get(f"/api/channels/{POSTERS}/history-scan")).json())["scan"]
        self.assertEqual((scan["state"], scan["done"], scan["action"]), ("done", 1, "delete_bot_posts"))
        rest.delete_message.assert_awaited_once_with(POSTERS, 61)
        entry = self.events("cleanup_completed")[0]
        self.assertEqual((entry["deleted"], entry["actor_id"], entry["via"]), (1, str(ALICE), "dashboard"))

    async def test_notifications_are_your_own_and_only_from_your_servers(self):
        both, theirs, mine = await self.item("both"), await self.item("theirs"), await self.item("mine")
        await self.post(both, POSTERS, self.alert_a["id"], 70)
        await self.post(both, VINYL, self.alert_b["id"], 71)
        await self.post(theirs, VINYL, self.alert_b["id"], 72)
        await self.post(mine, POSTERS, self.alert_a["id"], 73)
        for item in (both, theirs):
            await self.repository.subscribe(item, ALICE)
            await self.repository.subscribe(item, BOB)
        self.sign_in(ALICE)
        items = (await (await self.client.get("/api/me/notifications")).json())["items"]
        shown = {row["external_id"]: [(post["channel_id"], post["channel_name"]) for post in row["posts"]]
                 for row in items if not row.get("redacted")}
        # Only where Alice can look: the post in the other server is left out.
        self.assertEqual(shown, {"both": [(str(POSTERS), "posters")]})
        # What she follows only from a server she is not in is listed without its details.
        self.assertIn({"item_id": str(theirs), "redacted": True}, items)
        self.assertNotIn(str(BOB), json.dumps(items))
        response = await self.call("PUT", f"/api/me/notifications/{mine}")
        self.assertEqual(await response.json(), {"subscribed": True, "created": True})
        self.assertEqual(await (await self.call("PUT", f"/api/me/notifications/{mine}")).json(),
                         {"subscribed": True, "created": False})
        self.assertEqual((await self.call("DELETE", f"/api/me/notifications/{theirs}")).status, 200)
        self.assertEqual((await self.call("DELETE", f"/api/me/notifications/{theirs}")).status, 404)
        self.assertEqual(sorted(row["external_id"] for row in await self.repository.subscriptions(BOB)),
                         ["both", "theirs"])
        # Listings in the dashboard say whether you follow them, and nothing about others.
        await self.repository.archive_candidate(self.alert_a, {"id": "mine", "source": "yahooauction",
                                                               "title": "t", "price": 1, "stock": 1},
                                                {"verdict": "accepted", "normalized_title": "t", "reasons": [],
                                                 "normalization_version": 1})
        candidate = (await (await self.client.get("/api/candidates")).json())["items"][0]
        self.assertEqual((candidate["item_id"], candidate["subscribed"]), (str(mine), True))
        self.client.session.cookie_jar.clear()
        self.sign_in(BOB, {GUILD_A: Member((MANAGER,))})
        candidate = (await (await self.client.get("/api/candidates")).json())["items"][0]
        self.assertFalse(candidate["subscribed"])

    async def test_status_shows_each_searchs_checks_and_waiting_posts(self):
        item = await self.item("waiting")
        await self.repository._call("test_job", lambda: DeliveryJob.create(
            item=item, alert=self.alert_a["id"], kind="channel", destination_id=POSTERS, payload="{}"))
        self.sign_in(ALICE)
        status = await (await self.client.get(f"/api/guilds/{GUILD_A}/status")).json()
        self.assertEqual((status["bot_running"], status["bot"]), (False, None))
        searches = {row["search_query"]: row for row in status["searches"]}
        self.assertEqual(searches["BABYMETAL poster"]["backlog"]["pending"], 1)
        self.assertIsNone(searches["BABYMETAL poster"]["checks"])
        self.assertEqual(searches["BABYMETAL poster"]["channel_name"], "posters")
        check = {"source": "mercari", "outcome": "error", "finished_at": 1.0, "duration_seconds": 2.0,
                 "error": "ProviderError"}
        self.dashboard.runtime = SimpleNamespace(
            status=lambda: {"ready": True, "checks": {self.alert_a["id"]: [check]}},
            check_results={(self.alert_a["id"], "mercari"): check})
        status = await (await self.client.get(f"/api/guilds/{GUILD_A}/status")).json()
        searches = {row["search_query"]: row for row in status["searches"]}
        self.assertEqual(searches["BABYMETAL poster"]["checks"], [check])
        self.assertEqual(status["bot"], {"ready": True})
        guilds = (await (await self.client.get("/api/guilds")).json())["guilds"]
        self.assertEqual(guilds[0]["failing_searches"], 1)

    async def test_channel_ids_outside_your_servers_never_reach_discord(self):
        def channel_calls():
            return [path for _, path in self.fake.calls if path.startswith("/api/v10/channels/")]
        for members, levels in (({GUILD_A: Member((MANAGER,))}, None), ({GUILD_A: Member(())}, {GUILD_A: "member"})):
            self.client.session.cookie_jar.clear()
            self.sign_in(ALICE, members, levels)
            before = len(channel_calls())
            # Made-up IDs and another server's channel: answered from the servers' own channel lists.
            for channel in (987654321987654321, 987654321987654322, VINYL):
                for response in (await self.client.get(f"/api/channels/{channel}/hidden"),
                                 await self.call("POST", "/api/alerts", channel_id=str(channel), search_query="x")):
                    self.assertEqual(response.status, 404)
            self.assertEqual(channel_calls()[before:], [])
        # A channel with a search in a server you manage is looked up: Discord says it was deleted.
        self.client.session.cookie_jar.clear()
        self.sign_in(ALICE)
        self.assertEqual((await self.client.get(f"/api/channels/{GONE}/hidden")).status, 200)
        self.assertEqual(channel_calls()[-1], f"/api/v10/channels/{GONE}")

    async def test_the_access_key_has_no_notifications(self):
        cookie = self.dashboard.open_session(Session(time.monotonic() + 3600))
        self.client.session.cookie_jar.update_cookies({COOKIE: cookie})
        response = await self.client.get("/api/me/notifications")
        self.assertEqual(response.status, 403)
        self.assertIn("need Discord sign-in", (await response.json())["message"])


class WithoutDiscordTests(unittest.IsolatedAsyncioTestCase):
    """The standalone dashboard with the access key and no bot token: nothing is known from Discord."""

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = str(Path(self.directory.name) / "alerts.db")
        configure_database(path)
        create_tables()
        self.repository = Repository(Metrics())
        await self.repository.start()
        await self.repository.register_alert(POSTERS, "BABYMETAL poster", guild_id=GUILD_A)
        settings = replace(Settings(), database_path=path, dashboard_token="an-access-key-0123456789")
        self.dashboard = DashboardServer(settings, self.repository)
        self.client = TestClient(TestServer(self.dashboard.application("an-access-key-0123456789")),
                                 cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.headers = {"Origin": str(self.client.make_url("/")).rstrip("/")}
        await self.client.post("/api/login", json={"token": "an-access-key-0123456789"}, headers=self.headers)

    async def asyncTearDown(self):
        await self.client.close()
        await self.dashboard.close()
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    async def test_channels_are_listed_by_id_and_cannot_be_changed(self):
        session = await (await self.client.get("/api/session")).json()
        self.assertEqual(session["features"], {"notifications": False, "discord_data": False})
        guilds = (await (await self.client.get("/api/guilds")).json())["guilds"]
        self.assertEqual(guilds, [{"id": str(GUILD_A), "name": None, "icon_url": None, "level": "manager",
                                   "searches": 1, "failing_searches": 0, "failed_deliveries": 0}])
        body = await (await self.client.get(f"/api/guilds/{GUILD_A}/channels")).json()
        self.assertEqual((body["source"], body["unknown"]),
                         ("none", [{"id": str(POSTERS), "deleted": False, "searches": 1, "hidden": 0}]))
        self.assertEqual((await self.client.get(f"/api/channels/{POSTERS}/hidden")).status, 200)
        response = await self.client.post("/api/alerts", json={"channel_id": str(POSTERS), "search_query": "x"},
                                          headers=self.headers)
        self.assertEqual(response.status, 409)
        self.assertIn("need the bot's token", (await response.json())["message"])
