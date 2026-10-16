"""Discord sign-in, server permissions, revocation and per-server scoping, against a local fake Discord."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from aiohttp import ClientSession, CookieJar
from aiohttp.test_utils import TestClient, TestServer
import hikari
import pytest

from commands.base import ADMIN_PERMISSION
from config import Settings
from devtools.fake_discord import PERMISSIONS, FakeDiscord
from filtering import default_ruleset
from models import Item, Message, configure_database, create_tables, database
from observability import JsonFormatter, Metrics
from repositories import Repository
from review import ReviewServer
from review_auth import DiscordGuilds, DiscordOAuth, DiscordUnavailable, can_manage, guild_permissions

P = hikari.Permissions
SECRET = "fake-client-secret-0123456789abcdef"
BOT_TOKEN = "fake-bot-token"
GUILD_A, GUILD_B = 1100000000000000001, 1100000000000000002
MANAGER_A = 1200000000000000001
ALICE, BOB, CAROL, DAVE, ERIN = 1, 2, 3, 4, 5
INDEX = '<!doctype html><html><head><title>Filter Lab</title></head><body><div id="root"></div></body></html>'


def snowflake(moment):
    """A Discord message ID created at `moment`."""
    return (int(moment.timestamp() * 1000) - 1420070400000) << 22


def filter_everything():
    """Rules that filter every listing: a required group no title matches."""
    ruleset = default_ruleset()
    ruleset["groups"].append({"id": "never", "label": "never", "policy": "require", "match": "any",
                              "normalize": True, "terms": [{"method": "contains", "value": "never-in-a-title"}]})
    return ruleset


class GuildPermissionTests(unittest.TestCase):
    roles = {GUILD_A: P.VIEW_CHANNEL | P.SEND_MESSAGES, 10: P.MANAGE_CHANNELS, 11: P.MANAGE_MESSAGES,
             12: P.ADMINISTRATOR}

    def allowed(self, user_id, role_ids, roles=None, owner_id=999, timed_out=False):
        permissions = guild_permissions(user_id, owner_id, GUILD_A, roles or self.roles, role_ids, timed_out)
        return can_manage(permissions)

    def test_owner_holds_every_permission_without_roles(self):
        self.assertTrue(self.allowed(7, [], owner_id=7))
        self.assertEqual(guild_permissions(7, 7, GUILD_A, self.roles, []), P.all_permissions())

    def test_administrator_implies_manage_channels(self):
        self.assertTrue(self.allowed(7, [12]))

    def test_role_with_manage_channels_allows_and_role_without_it_does_not(self):
        self.assertTrue(self.allowed(7, [10]))
        self.assertFalse(self.allowed(7, [11]))
        self.assertFalse(self.allowed(7, []))

    def test_everyone_role_counts_for_every_member(self):
        roles = {**self.roles, GUILD_A: P.VIEW_CHANNEL | P.MANAGE_CHANNELS}
        self.assertTrue(self.allowed(7, [], roles=roles))
        self.assertTrue(self.allowed(7, [11], roles=roles))

    def test_unknown_roles_add_nothing(self):
        self.assertFalse(self.allowed(7, [404]))

    def test_timeout_removes_the_permission_except_for_administrators_and_owners(self):
        self.assertFalse(self.allowed(7, [10], timed_out=True))
        self.assertTrue(self.allowed(7, [12], timed_out=True))
        self.assertTrue(self.allowed(7, [], owner_id=7, timed_out=True))

    def test_the_gate_is_the_management_commands_permission(self):
        self.assertEqual(ADMIN_PERMISSION, P.MANAGE_CHANNELS)


def fake_discord():
    fake = FakeDiscord(client_secret=SECRET, bot_token=BOT_TOKEN)
    for user_id, name in ((ALICE, "alice"), (BOB, "bob"), (CAROL, "carol"), (DAVE, "dave"), (ERIN, "erin")):
        fake.add_user(user_id, name, name.title())
    first = fake.add_guild(GUILD_A, "Poster hunters", owner_id=DAVE)
    first.roles[MANAGER_A] = PERMISSIONS["manage_channels"]
    first.members.update({ALICE: [MANAGER_A], BOB: [], DAVE: [], ERIN: [MANAGER_A]})
    second = fake.add_guild(GUILD_B, "Record shop", owner_id=ERIN)
    second.members.update({ERIN: [], BOB: []})
    return fake


class FakeCache:
    """The parts of hikari's gateway cache DiscordGuilds reads."""

    def __init__(self, guilds):
        self.guilds = guilds

    def get_available_guild(self, guild_id):
        return self.guilds.get(guild_id, (None, None))[0]

    def get_roles_view_for_guild(self, guild_id):
        return self.guilds.get(guild_id, (None, {}))[1]


class DiscordGuildsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = fake_discord()
        await self.fake.start()
        self.rest_app = hikari.RESTApp(url=self.fake.api_url, max_retries=0)
        await self.rest_app.start()
        self.rest = self.rest_app.acquire(BOT_TOKEN, hikari.TokenType.BOT)
        self.rest.start()

    async def asyncTearDown(self):
        await self.rest.close()
        await self.rest_app.close()
        await self.fake.close()

    async def test_checks_membership_and_permission_in_every_server_with_the_bot_token(self):
        access = DiscordGuilds(self.rest)
        self.assertEqual((await access.check(ALICE)).guilds, {
            GUILD_A: {"id": str(GUILD_A), "name": "Poster hunters", "icon_url": None}})
        erin = await access.check(ERIN)
        self.assertEqual((set(erin.guilds), erin.member_of), ({GUILD_A, GUILD_B}, 2))
        bob = await access.check(BOB)
        self.assertEqual((bob.guilds, bob.member_of), ({}, 2))
        carol = await access.check(CAROL)
        self.assertEqual((carol.guilds, carol.member_of), ({}, 0))
        dave = await access.check(DAVE)
        self.assertEqual(set(dave.guilds), {GUILD_A})
        self.assertEqual(await access.application_id(), 900000000000000001)

    async def test_roles_and_owner_come_from_the_gateway_cache_when_it_has_them(self):
        guild = type("Guild", (), {"owner_id": DAVE})()
        role = type("Role", (), {})
        everyone, manager = role(), role()
        everyone.permissions, manager.permissions = P.VIEW_CHANNEL, P.MANAGE_CHANNELS
        access = DiscordGuilds(self.rest, FakeCache({GUILD_A: (guild, {GUILD_A: everyone, MANAGER_A: manager})}))
        self.assertEqual(set((await access.check(ALICE)).guilds), {GUILD_A})
        fetched = [path for _, path in self.fake.calls if path.startswith("/api/v10/guilds/") and "/members/" not in path]
        self.assertEqual(fetched, [])
        # The member always comes from REST: the bot has no members intent.
        self.assertIn(("GET", f"/api/v10/guilds/{GUILD_A}/members/{ALICE}"), self.fake.calls)

    async def test_fails_closed_when_discord_is_down_or_slow(self):
        access = DiscordGuilds(self.rest, timeout=0.2)
        self.fake.down = True
        with self.assertRaises(DiscordUnavailable):
            await access.check(ALICE)
        with self.assertRaises(DiscordUnavailable):
            await access.application_id()
        self.fake.down, self.fake.delay = False, 1
        with self.assertRaises(DiscordUnavailable):
            await access.check(ALICE)


class DiscordSignInTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "review.db")
        configure_database(self.path)
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(31, "BABYMETAL poster", guild_id=GUILD_A)
        await self.repository.register_alert(32, "Vinyl", guild_id=GUILD_B)
        # A legacy alert whose server was never found: Discord users never see it.
        await self.repository.register_alert(33, "Legacy", guild_id=None)
        # The API sends IDs as strings.
        alerts = {alert["search_query"]: {**alert, "id": str(alert["id"])}
                  for alert in await self.repository.list_alerts()}
        self.alert_a, self.alert_b, self.legacy = alerts["BABYMETAL poster"], alerts["Vinyl"], alerts["Legacy"]
        for alert, title in ((self.alert_a, "BABYMETAL poster"), (self.alert_b, "Vinyl record"),
                             (self.legacy, "Legacy poster")):
            await self.repository.archive_candidate(alert, {"id": f"{alert['id']}-1", "source": "yahooauction",
                                                            "title": title, "price": 1000, "stock": 1},
                                                    {"verdict": "accepted", "normalized_title": title.lower(),
                                                     "reasons": [], "normalization_version": 1})
        self.version_b = await self.repository.publish_review_rules(self.alert_b["id"], default_ruleset())

        self.fake = fake_discord()
        await self.fake.start()
        self.rest_app = hikari.RESTApp(url=self.fake.api_url, max_retries=0)
        await self.rest_app.start()
        self.rest = self.rest_app.acquire(BOT_TOKEN, hikari.TokenType.BOT)
        self.rest.start()

        # The real address is known once the test server listens; port 0 lets the system pick one.
        settings = replace(Settings(), token=BOT_TOKEN, database_path=self.path,
                           review_public_url="http://127.0.0.1:1", review_discord_client_secret=SECRET,
                           review_port=0)
        assets = Path(self.directory.name) / "dist"
        assets.mkdir()
        (assets / "index.html").write_text(INDEX, encoding="utf-8")
        oauth = DiscordOAuth.from_settings(settings, authorize_url=self.fake.authorize_url, api_url=self.fake.api_url,
                                           cdn_url=self.fake.base_url)
        self.review = ReviewServer(settings, self.repository, self.metrics, assets=assets,
                                   guild_access=DiscordGuilds(self.rest), oauth=oauth)
        self.client = TestClient(TestServer(self.review.application(), host="127.0.0.1"),
                                 cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.public = f"http://127.0.0.1:{self.client.port}"
        self.review.public_url, oauth.redirect_uri = self.public, self.public + "/auth/discord/callback"
        self.headers = {"Origin": self.public}
        self.logs = []
        handler = logging.Handler()
        # The formatter without secrets to hide: the raw output must not contain any.
        handler.emit = lambda record: self.logs.append(JsonFormatter().format(record))
        handler.setLevel(logging.DEBUG)
        self.handler = handler
        for name in ("review", "review_auth"):
            logging.getLogger(name).addHandler(handler)
            logging.getLogger(name).setLevel(logging.DEBUG)

    async def asyncTearDown(self):
        for name in ("review", "review_auth"):
            logging.getLogger(name).removeHandler(self.handler)
        await self.client.close()
        await self.review.close()
        await self.rest.close()
        await self.rest_app.close()
        await self.fake.close()
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    def events(self, name):
        return [entry for entry in map(json.loads, self.logs) if entry["event"] == name]

    def logins(self, outcome):
        return self.metrics.registry.get_sample_value(
            "auction_bot_review_logins_total", {"method": "discord", "outcome": outcome})

    async def start(self, next_page="/?alert=1&tab=rules"):
        response = await self.client.get("/auth/discord", params={"next": next_page}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        return response

    async def callback(self, url):
        parts = urlsplit(url)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", self.public + "/auth/discord/callback")
        return await self.client.get(f"{parts.path}?{parts.query}", allow_redirects=False)

    async def sign_in(self, user_id):
        location = (await self.start()).headers["Location"]
        response = await self.callback(self.fake.approve(location, user_id))
        self.assertEqual(response.status, 200)
        finish = await self.client.get("/auth/discord/finish", params={"next": "/?alert=1&tab=rules"},
                                       allow_redirects=False)
        self.assertEqual((finish.status, finish.headers["Location"]), (303, "/?alert=1&tab=rules"))
        return response

    def denied(self, response, reason):
        self.assertEqual((response.status, response.headers["Location"]), (303, f"/?signin={reason}"))
        self.assertNotIn("filter_lab_session", response.cookies)

    def expire_access_checks(self):
        for session in self.review.sessions.values():
            session.checked -= 301

    async def test_sign_in_uses_a_lax_handshake_cookie_then_a_strict_session_after_a_same_site_hop(self):
        start = await self.start()
        location = start.headers["Location"]
        query = parse_qs(urlsplit(location).query)
        self.assertTrue(location.startswith(self.fake.authorize_url + "?"))
        self.assertEqual({name: query[name][0] for name in (
            "response_type", "scope", "client_id", "redirect_uri", "code_challenge_method")}, {
            "response_type": "code", "scope": "identify", "client_id": "900000000000000001",
            "redirect_uri": self.public + "/auth/discord/callback", "code_challenge_method": "S256"})
        # Discord shows its consent screen every time; prompt=none is not sent.
        self.assertNotIn("prompt", query)
        handshake = start.cookies["filter_lab_login"]
        self.assertEqual((handshake["samesite"], handshake["path"], bool(handshake["httponly"])),
                         ("Lax", "/auth/discord", True))
        self.assertNotIn(handshake.value, location)

        callback = await self.callback(self.fake.approve(location, ALICE))
        self.assertEqual(callback.status, 200)
        session = callback.cookies["filter_lab_session"]
        self.assertEqual((session["samesite"], session["path"], bool(session["httponly"])), ("Strict", "/", True))
        self.assertEqual(callback.cookies["filter_lab_login"]["max-age"], "0")
        # The page moves on with a refresh from Filter Lab's own address instead of a redirect.
        page = await callback.text()
        self.assertIn('http-equiv="refresh" content="0; url=/auth/discord/finish?next=%2F%3Falert%3D1%26tab%3Drules"',
                      page.replace("&amp;", "&"))
        finish = await self.client.get("/auth/discord/finish", params={"next": "/?alert=1&tab=rules"},
                                       allow_redirects=False)
        self.assertEqual((finish.status, finish.headers["Location"]), (303, "/?alert=1&tab=rules"))

        body = await (await self.client.get("/api/session")).json()
        self.assertEqual((body["authenticated"], body["method"]), (True, "discord"))
        self.assertEqual(body["user"], {"id": str(ALICE), "name": "Alice", "username": "alice",
                                        "avatar_url": self.fake.base_url + "/embed/avatars/0.png"})
        self.assertEqual(body["guilds"], [{"id": str(GUILD_A), "name": "Poster hunters", "icon_url": None}])
        self.assertEqual(self.logins("success"), 1)
        self.assertEqual(self.events("review_login_succeeded")[0]["actor_id"], str(ALICE))
        # The access token was revoked at Discord after its one use.
        self.assertEqual((len(self.fake.issued), self.fake.tokens), (1, {}))
        # Neither the code, the token, the PKCE verifier nor the client secret is logged.
        output = "\n".join(self.logs)
        for value in [SECRET, *self.fake.issued, query["state"][0], handshake.value, session.value]:
            self.assertNotIn(value, output)

    async def test_the_session_survives_behind_a_tls_proxy_with_secure_cookies(self):
        self.review.public_url = self.public.replace("http:", "https:")
        response = await self.client.get("/auth/discord", headers={"X-Forwarded-Proto": "https"},
                                         allow_redirects=False)
        self.assertTrue(response.cookies["filter_lab_login"]["secure"])

    async def test_a_proxy_that_hides_https_gets_a_clear_error_instead_of_a_redirect_loop(self):
        self.review.public_url = self.public.replace("http:", "https:")
        response = await self.client.get("/auth/discord", allow_redirects=False)
        self.assertEqual(response.status, 500)
        self.assertIn("X-Forwarded-Proto: https", await response.text())
        self.assertNotIn("filter_lab_login", response.cookies)

    async def test_sign_in_starts_over_on_the_public_address(self):
        response = await self.client.get("/auth/discord", params={"next": "/?tab=rules"},
                                         headers={"Host": "filterlab.internal:9101"}, allow_redirects=False)
        self.assertEqual(response.headers["Location"], self.public + "/auth/discord?next=%2F%3Ftab%3Drules")
        self.assertNotIn("filter_lab_login", response.cookies)
        # Only Filter Lab's own page is a place to come back to.
        location = (await self.start(next_page="//evil.example/")).headers["Location"]
        page = await (await self.callback(self.fake.approve(location, ALICE))).text()
        self.assertIn("url=/auth/discord/finish?next=%2F\"", page)

    async def test_each_denial_has_its_own_reason_and_creates_no_session(self):
        # Cancelled on Discord's consent screen.
        self.denied(await self.callback(self.fake.cancel((await self.start()).headers["Location"])), "cancelled")
        # Not in any server the bot is in.
        self.denied(await self.callback(self.fake.approve((await self.start()).headers["Location"], CAROL)),
                    "not_member")
        # In servers, but without Manage Channels in any of them.
        self.denied(await self.callback(self.fake.approve((await self.start()).headers["Location"], BOB)),
                    "missing_permission")
        # Discord does not answer.
        location = (await self.start()).headers["Location"]
        self.fake.down = True
        self.denied(await self.callback(self.fake.approve(location, ALICE)), "discord_unavailable")
        self.fake.down = False
        self.assertEqual({entry["reason"]: entry["actor_id"] for entry in self.events("review_login_denied")}, {
            "cancelled": None, "not_member": str(CAROL), "missing_permission": str(BOB),
            "discord_unavailable": None})
        for reason in ("cancelled", "not_member", "missing_permission", "discord_unavailable"):
            self.assertEqual(self.logins(reason), 1)
        self.assertEqual(self.review.sessions, {})

    async def test_bad_expired_reused_or_foreign_state_is_refused(self):
        # States Filter Lab never issued, or changed ones.
        location = (await self.start()).headers["Location"]
        callback = self.fake.approve(location, ALICE)
        state = parse_qs(urlsplit(callback).query)["state"][0]
        issued, signature = state.split(".")
        # A signature's last character is one of 16; swap it for another so it always changes.
        tampered = signature[:-1] + ("E" if signature.endswith("A") else "A")
        for forged in ("forged-state", f"{int(issued) + 1}.{signature}", f"{issued}.{tampered}"):
            self.denied(await self.callback(callback.replace(state, forged)), "state")
        # The real state still works once: the callback removes the login cookie.
        self.assertEqual((await self.callback(callback)).status, 200)
        self.denied(await self.callback(callback), "state")
        # Expired.
        location = (await self.start()).headers["Location"]
        self.review.login_seconds = -1
        self.denied(await self.callback(self.fake.approve(location, ALICE)), "state")
        self.review.login_seconds = 600
        # Started in another browser: the login cookie is missing.
        location = (await self.start()).headers["Location"]
        self.client.session.cookie_jar.clear(lambda cookie: cookie.key == "filter_lab_login")
        self.denied(await self.callback(self.fake.approve(location, ALICE)), "state")
        # Started in another tab: a later sign-in replaced the login cookie.
        first = (await self.start()).headers["Location"]
        await self.start()
        self.denied(await self.callback(self.fake.approve(first, ALICE)), "state")
        self.assertEqual([entry["detail"] for entry in self.events("review_login_denied")],
                         ["invalid", "mismatch", "mismatch", "other_browser", "expired", "other_browser", "mismatch"])

    async def test_many_sign_ins_started_elsewhere_do_not_break_one_in_progress(self):
        location = (await self.start()).headers["Location"]
        # Another browser starts 300 sign-ins; the server keeps nothing for them.
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as other:
            for _ in range(300):
                async with other.get(self.public + "/auth/discord", allow_redirects=False) as response:
                    self.assertEqual(response.status, 302)
        self.assertEqual((await self.callback(self.fake.approve(location, ALICE))).status, 200)

    async def test_a_code_discord_does_not_accept_is_refused(self):
        location = (await self.start()).headers["Location"]
        callback = self.fake.approve(location, ALICE)
        self.fake.codes.clear()
        self.denied(await self.callback(callback), "discord_error")
        self.assertEqual(self.events("review_login_denied")[0]["detail"], "invalid_grant")

    async def test_the_last_step_reports_a_session_cookie_the_browser_did_not_send(self):
        self.denied(await self.client.get("/auth/discord/finish", allow_redirects=False), "cookie")

    async def test_failed_sign_ins_are_rate_limited_but_broken_links_do_not_count(self):
        # Anyone can send broken links; they must not block sign-in for everyone.
        for _ in range(20):
            self.denied(await self.client.get("/auth/discord/callback", params={"state": "x", "code": "y"},
                                              allow_redirects=False), "state")
        # Sign-ins that Discord sent back and that then failed do count.
        for _ in range(10):
            self.denied(await self.callback(self.fake.cancel((await self.start()).headers["Location"])), "cancelled")
        self.denied(await self.client.get("/auth/discord", allow_redirects=False), "rate_limited")
        self.denied(await self.client.get("/auth/discord/callback", params={"state": "x", "code": "y"},
                                          allow_redirects=False), "rate_limited")
        self.assertEqual(self.logins("rate_limited"), 2)
        # Refusals while blocked are counted, and logged only at debug level.
        self.assertEqual({(entry["reason"], entry["level"]) for entry in self.events("review_login_denied")},
                         {("state", "WARNING"), ("cancelled", "WARNING"), ("rate_limited", "DEBUG")})

    async def test_one_person_cannot_push_out_everyone_elses_sessions(self):
        await self.sign_in(ERIN)
        erin = next(cookie.value for cookie in self.client.session.cookie_jar if cookie.key == "filter_lab_session")
        for _ in range(7):
            await self.sign_in(ALICE)
        users = [session.user["id"] for session in self.review.sessions.values()]
        self.assertEqual((users.count(str(ALICE)), users.count(str(ERIN))), (5, 1))
        self.assertIn(erin, self.review.sessions)

    async def test_the_access_key_is_turned_off(self):
        response = await self.client.post("/api/login", json={"token": "anything-at-all-123"}, headers=self.headers)
        self.assertEqual(response.status, 404)
        self.assertNotIn("filter_lab_session", response.cookies)
        self.assertEqual(await (await self.client.get("/api/session")).json(),
                         {"authenticated": False, "method": "discord"})
        self.assertEqual((await (await self.client.get("/api/alerts")).json())["message"], "Sign in with Discord")
        await self.review.start()
        self.assertFalse(Path(self.path + ".review-token").exists())

    async def test_access_is_checked_again_only_after_five_minutes(self):
        await self.sign_in(ALICE)
        calls = len(self.fake.calls)
        self.fake.guilds[GUILD_A].members.pop(ALICE)
        for _ in range(5):
            self.assertEqual((await self.client.get("/api/alerts")).status, 200)
        self.assertEqual(len(self.fake.calls), calls)
        self.expire_access_checks()
        # Requests at the same moment share one check.
        responses = await asyncio.gather(*(self.client.get("/api/alerts") for _ in range(4)))
        self.assertEqual({response.status for response in responses}, {401})
        self.assertEqual({(await response.json())["error"] for response in responses}, {"access_revoked"})
        self.assertEqual(self.fake.calls[calls:].count(("GET", f"/api/v10/guilds/{GUILD_A}/members/{ALICE}")), 1)
        self.assertEqual(self.review.sessions, {})
        revoked = self.events("review_access_revoked")[0]
        self.assertEqual((revoked["actor_id"], revoked["guild_ids"], revoked["session_ended"]),
                         (str(ALICE), [str(GUILD_A)], True))
        # A reload still says why, until the person signs out or signs in again.
        response = await self.client.get("/api/alerts")
        self.assertEqual((response.status, (await response.json())["error"]), (401, "access_revoked"))
        self.assertEqual(await (await self.client.get("/api/session")).json(),
                         {"authenticated": False, "method": "discord", "reason": "access_revoked"})
        await self.client.delete("/api/session", headers=self.headers)
        self.assertEqual(await (await self.client.get("/api/session")).json(),
                         {"authenticated": False, "method": "discord"})

    async def test_losing_the_role_in_one_server_removes_only_that_server(self):
        await self.sign_in(ERIN)
        alerts = await (await self.client.get("/api/alerts")).json()
        self.assertEqual({alert["id"] for alert in alerts["alerts"]}, {self.alert_a["id"], self.alert_b["id"]})
        self.fake.guilds[GUILD_A].members[ERIN] = []
        self.expire_access_checks()
        alerts = await (await self.client.get("/api/alerts")).json()
        self.assertEqual([alert["id"] for alert in alerts["alerts"]], [self.alert_b["id"]])
        self.assertEqual((await self.client.get(f"/api/alerts/{self.alert_a['id']}/rules")).status, 404)
        session = await (await self.client.get("/api/session")).json()
        self.assertEqual([guild["id"] for guild in session["guilds"]], [str(GUILD_B)])
        self.assertEqual(self.metrics.registry.get_sample_value(
            "auction_bot_review_access_checks_total", {"outcome": "reduced"}), 1)

    async def test_session_reports_revocation_when_it_is_the_request_that_finds_it(self):
        await self.sign_in(ALICE)
        self.fake.guilds[GUILD_A].members[ALICE] = []
        self.expire_access_checks()
        self.assertEqual(await (await self.client.get("/api/session")).json(),
                         {"authenticated": False, "method": "discord", "reason": "access_revoked"})

    async def test_unreachable_discord_fails_closed_and_waits_before_asking_again(self):
        await self.sign_in(ALICE)
        self.expire_access_checks()
        self.fake.down = True
        response = await self.client.get("/api/alerts")
        self.assertEqual((response.status, (await response.json())["error"]), (503, "access_unknown"))
        calls = len(self.fake.calls)
        self.fake.down = False
        self.assertEqual((await self.client.get("/api/alerts")).status, 503)
        self.assertEqual(len(self.fake.calls), calls)
        for session in self.review.sessions.values():
            session.failed -= 31
        self.assertEqual((await self.client.get("/api/alerts")).status, 200)
        self.assertEqual(self.events("review_access_check_failed")[0]["actor_id"], str(ALICE))

    async def test_every_endpoint_is_limited_to_the_servers_the_person_manages(self):
        await self.sign_in(ALICE)
        a, b = self.alert_a["id"], self.alert_b["id"]
        everything = await self.repository.list_candidates()
        rows = {row["alert_id"]: row["id"] for row in everything["items"]}
        mine, theirs, legacy = rows[a], rows[b], rows[self.legacy["id"]]
        missing_alert = await (await self.client.get("/api/alerts/999999/rules")).json()
        tested = set()

        async def check(name, response, status=404):
            tested.add(name)
            self.assertEqual(response.status, status, name)
            if status == 404:
                # Exactly what a missing alert gets, so other servers' alerts are not revealed.
                self.assertEqual(await response.json(), missing_alert, name)

        body = await (await self.client.get("/api/alerts")).json()
        tested.add("alerts")
        self.assertEqual([alert["id"] for alert in body["alerts"]], [a])
        self.assertEqual(body["totals"], {"archived_count": 1, "unassigned_count": 0,
                                          "guilds": {str(GUILD_A): {"archived_count": 1, "unassigned_count": 0}}})
        await check("rules", await self.client.get(f"/api/alerts/{b}/rules"))
        await check("rules", await self.client.get(f"/api/alerts/{self.legacy['id']}/rules"))
        await check("candidates", await self.client.get("/api/candidates", params={"alert_id": b}))
        listed = await (await self.client.get("/api/candidates", params={"latest": "1", "facets": "1"})).json()
        self.assertEqual(([row["id"] for row in listed["items"]], listed["total"]), ([mine], 1))
        self.assertEqual(listed["facets"]["verdict"]["accepted"], 1)
        found = await (await self.client.get("/api/candidates", params={"search": "Vinyl"})).json()
        self.assertEqual(found["items"], [])
        response = await self.client.get("/api/candidates", params={"guild_id": GUILD_B})
        self.assertEqual(response.status, 404)
        response = await self.client.get("/api/candidates", params={"guild_id": GUILD_A})
        self.assertEqual([row["id"] for row in (await response.json())["items"]], [mine])
        response = await self.client.post(f"/api/candidates/{theirs}/feedback", json={"label": "bundle"},
                                          headers=self.headers)
        tested.add("feedback")
        self.assertEqual((response.status, (await response.json())["message"]), (404, "Candidate no longer exists"))
        response = await self.client.post("/api/candidates/feedback", json={
            "ids": [mine, theirs, legacy], "label": "bundle"}, headers=self.headers)
        tested.add("feedback_bulk")
        result = await response.json()
        self.assertEqual(([row["id"] for row in result["items"]], result["missing"]), ([mine], [theirs, legacy]))
        labels = {row["id"]: row["feedback"] for row in (await self.repository.list_candidates())["items"]}
        self.assertEqual((labels[theirs], labels[legacy]), (None, None))
        await check("preview", await self.client.post("/api/preview", json={
            "ruleset": default_ruleset(), "title": "x", "alert_id": b}, headers=self.headers))
        await check("replay", await self.client.post("/api/replay", json={
            "alert_id": b, "ruleset": default_ruleset()}, headers=self.headers))
        await check("publish", await self.client.post(f"/api/alerts/{b}/publish", json={
            "ruleset": default_ruleset(), "expected_version_id": self.version_b["id"]}, headers=self.headers))
        await check("rollback", await self.client.post(f"/api/alerts/{b}/rollback", json={
            "version_id": self.version_b["id"], "expected_version_id": self.version_b["id"]}, headers=self.headers))
        response = await self.client.post(f"/api/alerts/{a}/rollback", json={
            "version_id": self.version_b["id"], "expected_version_id": None}, headers=self.headers)
        self.assertEqual(response.status, 404)
        self.assertEqual((await self.repository.get_review_rules(b))["versions_total"], 1)
        response = await self.client.post("/api/rules/validate", json={"ruleset": default_ruleset()},
                                          headers=self.headers)
        tested.add("rules_validate")
        self.assertEqual(response.status, 200)
        response = await self.client.post("/api/history/import", json={}, headers=self.headers)
        tested.add("history_import")
        self.assertEqual(response.status, 200)
        for alert in (b, self.legacy["id"]):
            await check("post_removal_preview", await self.client.post(
                f"/api/alerts/{alert}/posts/removal-preview", json={"days": 30}, headers=self.headers))
            await check("post_removal", await self.client.post(f"/api/alerts/{alert}/posts/removal", json={
                "version_id": self.version_b["id"], "message_ids": ["1"]}, headers=self.headers))
            await check("post_removal_status", await self.client.get(f"/api/alerts/{alert}/posts/removal"))
        # Every data route of the API is covered here; a new route must be added to this test.
        routes = {route.name for route in self.client.app.router.routes()
                  if route.resource.canonical.startswith("/api/")} - {"session", "logout"}
        self.assertEqual(routes, tested)

    async def test_post_removal_previews_and_queues_only_in_the_persons_servers(self):
        now = datetime.now(timezone.utc)
        posts = {}

        def create():
            for index, alert in enumerate((self.alert_a, self.alert_b)):
                item = Item.create(item_id=f"post-{alert['id']}", checker="yahooauction", title="Vinyl record",
                                   price=1000)
                posts[alert["id"]] = snowflake(now - timedelta(hours=index + 1))
                Message.create(message_id=posts[alert["id"]], item=item, alert=int(alert["id"]),
                               channel_id=alert["channel_id"])
        await self.repository._call("test_posts", create)
        a, b = self.alert_a["id"], self.alert_b["id"]
        version_a = await self.repository.publish_review_rules(a, filter_everything(), None)
        version_b = await self.repository.publish_review_rules(b, filter_everything(), self.version_b["id"])
        await self.sign_in(ALICE)
        missing = await (await self.client.get("/api/alerts/999999/rules")).json()

        # Their own server: preview, queue and progress work.
        preview = await self.client.post(f"/api/alerts/{a}/posts/removal-preview", json={"days": 30},
                                         headers=self.headers)
        self.assertEqual([post["message_id"] for post in (await preview.json())["posts"]], [str(posts[a])])
        queued = await self.client.post(f"/api/alerts/{a}/posts/removal", json={
            "version_id": version_a["id"], "message_ids": [str(posts[a])]}, headers=self.headers)
        self.assertEqual(await queued.json(), {"queued": 1, "skipped": 0, "bot_running": False})
        status = await (await self.client.get(f"/api/alerts/{a}/posts/removal")).json()
        self.assertEqual(status["run"]["total"], 1)

        # Another server: refused like a missing search, and nothing is queued there.
        for response in (
                await self.client.post(f"/api/alerts/{b}/posts/removal-preview", json={"days": 30},
                                       headers=self.headers),
                await self.client.post(f"/api/alerts/{b}/posts/removal", json={
                    "version_id": version_b["id"], "message_ids": [str(posts[b])]}, headers=self.headers),
                await self.client.get(f"/api/alerts/{b}/posts/removal")):
            self.assertEqual((response.status, await response.json()), (404, missing))
        self.assertEqual((await self.repository.post_removal_status(b))["run"], None)
        logged = self.events("review_post_removal_queued")
        self.assertEqual([(entry["actor_id"], entry["sign_in"], entry["alert_id"], entry["guild_id"], entry["queued"])
                          for entry in logged], [(str(ALICE), "discord", a, str(GUILD_A), 1)])

    async def test_import_takes_only_the_persons_servers(self):
        from models import AlertItem, Item

        def observe():
            for alert in (self.alert_a, self.alert_b):
                item = Item.create(item_id=f"import-{alert['id']}", checker="yahooauction", title="t")
                AlertItem.create(alert=int(alert["id"]), item=item, stock=1, price=1000, buyout_price=0)
        await self.repository._call("test_observe", observe)
        await self.sign_in(ALICE)
        response = await self.client.post("/api/history/import", json={}, headers=self.headers)
        self.assertEqual((await response.json())["imported"], 1)
        rows = (await self.repository.list_candidates(search="import-"))["items"]
        self.assertEqual([row["alert_id"] for row in rows], [self.alert_a["id"]])

    async def test_changes_are_logged_with_the_discord_user(self):
        await self.sign_in(ALICE)
        a = self.alert_a["id"]
        mine = (await self.repository.list_candidates(alert_id=a))["items"][0]["id"]
        await self.client.post(f"/api/candidates/{mine}/feedback", json={"label": "relevant"}, headers=self.headers)
        await self.client.post("/api/candidates/feedback", json={"ids": [mine], "label": None}, headers=self.headers)
        first = await (await self.client.post(f"/api/alerts/{a}/publish", json={
            "ruleset": default_ruleset(), "expected_version_id": None}, headers=self.headers)).json()
        second = await (await self.client.post(f"/api/alerts/{a}/publish", json={
            "ruleset": default_ruleset(), "expected_version_id": first["id"]}, headers=self.headers)).json()
        await self.client.post(f"/api/alerts/{a}/rollback", json={
            "version_id": first["id"], "expected_version_id": second["id"]}, headers=self.headers)
        await self.client.post("/api/history/import", json={}, headers=self.headers)
        for event in ("review_labels_changed", "review_rules_published", "review_rules_restored",
                      "review_history_imported"):
            entries = self.events(event)
            self.assertTrue(entries, event)
            self.assertEqual({(entry["actor_id"], entry["sign_in"]) for entry in entries},
                             {(str(ALICE), "discord")}, event)
        labels = self.events("review_labels_changed")
        self.assertEqual([(entry["label"], entry["guild_ids"]) for entry in labels],
                         [("relevant", [str(GUILD_A)]), (None, [str(GUILD_A)])])

    async def test_sign_out_ends_the_session(self):
        await self.sign_in(ALICE)
        response = await self.client.delete("/api/session", headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.client.get("/api/alerts")).status, 401)
        self.assertEqual(self.events("review_logout")[0]["actor_id"], str(ALICE))


def configure(monkeypatch, **values):
    for name in ("BOT_TOKEN", "REVIEW_TOKEN", "REVIEW_TOKEN_FILE", "REVIEW_PUBLIC_URL",
                 "REVIEW_DISCORD_CLIENT_SECRET", "REVIEW_DISCORD_CLIENT_SECRET_FILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_discord_sign_in_settings_are_checked_at_startup(monkeypatch, tmp_path):
    configure(monkeypatch, BOT_TOKEN="token", REVIEW_PUBLIC_URL="https://Yahoo.Internal.Waxdt.com:443/",
              REVIEW_DISCORD_CLIENT_SECRET=SECRET)
    settings = Settings.from_env()
    assert (settings.review_public_url, settings.discord_sign_in) == ("https://yahoo.internal.waxdt.com", True)
    assert SECRET not in repr(settings)
    secret_file = tmp_path / "client-secret"
    secret_file.write_text(SECRET + "\n")
    configure(monkeypatch, BOT_TOKEN="token", REVIEW_PUBLIC_URL="http://127.0.0.1:9101",
              REVIEW_DISCORD_CLIENT_SECRET_FILE=str(secret_file))
    assert Settings.from_env().review_discord_client_secret == SECRET
    configure(monkeypatch, BOT_TOKEN="token")
    assert not Settings.from_env().discord_sign_in
    for values, message in (
        ({"REVIEW_DISCORD_CLIENT_SECRET": SECRET}, "needs REVIEW_PUBLIC_URL"),
        ({"REVIEW_PUBLIC_URL": "https://filterlab.example.com"}, "also set REVIEW_DISCORD_CLIENT_SECRET"),
        ({"REVIEW_PUBLIC_URL": "http://filterlab.example.com", "REVIEW_DISCORD_CLIENT_SECRET": SECRET}, "https://"),
        ({"REVIEW_PUBLIC_URL": "https://filterlab.example.com/lab", "REVIEW_DISCORD_CLIENT_SECRET": SECRET},
         "site address only"),
        ({"REVIEW_PUBLIC_URL": "https://filterlab.example.com", "REVIEW_DISCORD_CLIENT_SECRET": "short"},
         "not a Discord client secret"),
        ({"REVIEW_PUBLIC_URL": "https://filterlab.example.com", "REVIEW_DISCORD_CLIENT_SECRET": SECRET,
          "REVIEW_DISCORD_CLIENT_SECRET_FILE": str(secret_file)}, "not both"),
        ({"REVIEW_PUBLIC_URL": "https://filterlab.example.com",
          "REVIEW_DISCORD_CLIENT_SECRET_FILE": str(tmp_path / "missing")}, "cannot be read"),
        ({"REVIEW_PUBLIC_URL": "https://filterlab.example.com", "REVIEW_DISCORD_CLIENT_SECRET": SECRET,
          "REVIEW_TOKEN": "an-access-key-that-is-long"}, "remove REVIEW_TOKEN"),
    ):
        configure(monkeypatch, BOT_TOKEN="token", **values)
        with pytest.raises(ValueError, match=message):
            Settings.from_env()
    configure(monkeypatch, REVIEW_PUBLIC_URL="https://filterlab.example.com", REVIEW_DISCORD_CLIENT_SECRET=SECRET)
    with pytest.raises(ValueError, match="needs BOT_TOKEN"):
        Settings.from_env(require_token=False)


def test_the_client_secret_and_oauth_tokens_are_redacted_from_logs():
    formatter = JsonFormatter(secrets=(SECRET,))
    record = logging.LogRecord("review", logging.INFO, __file__, 1, "using %s", (SECRET,), None)
    record.fields = {"client_secret": "a", "access_token": "b", "refresh_token": "c", "code_verifier": "d"}
    encoded = formatter.format(record)
    assert SECRET not in encoded
    assert set(json.loads(encoded)[key] for key in record.fields) == {"[redacted]"}


def test_the_bot_wires_discord_sign_in_to_its_rest_client_and_cache(tmp_path, monkeypatch):
    import main
    import observability

    captured = {}
    monkeypatch.setattr(observability, "configure_logging", lambda level, secrets=(): captured.update(secrets=secrets))
    settings = replace(Settings(), token="MTIzNDU2Nzg5.MOCK.MOCK", database_path=str(tmp_path / "bot.db"),
                       monitoring_enabled=False, review_public_url="https://filterlab.example.com",
                       review_discord_client_secret=SECRET)
    bot = main.create_application(settings)
    review = bot.services.runtime.review
    assert SECRET in captured["secrets"]
    assert (review.guild_access.rest, review.guild_access.cache) == (bot.rest, bot.cache)
    assert review.oauth.redirect_uri == "https://filterlab.example.com/auth/discord/callback"
    asyncio.run(bot.services.runtime.close())
