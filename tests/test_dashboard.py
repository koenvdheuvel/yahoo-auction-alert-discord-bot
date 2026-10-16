"""Real dashboard HTTP flows, live ingestion and replay isolation on temporary SQLite."""
from dataclasses import replace
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import unittest
from types import SimpleNamespace

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from config import Settings
from filtering import default_ruleset
from domain import Listing
from models import Item, configure_database, create_tables, database
from observability import Metrics
from providers import YahooAuctionsAdapter
from repositories import Repository
from dashboard import NONCE_PLACEHOLDER, DashboardServer, dashboard_key
from dashboard_limits import parse_proxies
from storechecker import Ingestion


TOKEN = "dashboard-test-access-key-123456789"
INDEX = (f'<!doctype html><html><head><meta property="csp-nonce" nonce="{NONCE_PLACEHOLDER}">'
         '<title>Dashboard</title><script type="module" crossorigin src="/assets/index-abc123.js"></script>'
         '</head><body><div id="root"></div></body></html>')


def snowflake(moment):
    """A Discord message ID created at `moment`."""
    return (int(moment.timestamp() * 1000) - 1420070400000) << 22


def product_rules():
    result = default_ruleset()
    for name, terms, policy in (
        ("subject", ["BABYMETAL", "ベビーメタル"], "require"),
        ("product", ["poster", "ポスター"], "require"),
        ("exclude", ["フレームのみ", "まとめ売り"], "exclude"),
    ):
        result["groups"].append({"id": name, "label": name, "policy": policy,
            "match": "any", "normalize": True,
            "terms": [{"method": "contains", "value": term} for term in terms]})
    return result


class MemoryProvider:
    source = "yahooauction"

    def __init__(self, rows):
        self.rows = rows
        self.normalize = YahooAuctionsAdapter(SimpleNamespace(), Settings()).normalize

    async def iter_items(self, query):
        for row in self.rows:
            yield row


class Names:
    """A channel directory that only knows names, from a function of the channel IDs."""
    available = False

    def __init__(self, names):
        self.lookup = names

    async def names(self, channel_ids, guild_ids=()):
        return self.lookup(channel_ids)

    async def bot(self):
        return None


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "alerts.db")
        configure_database(self.path)
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(9007199254740993, "BABYMETAL posters", guild_id=9007199254740995)
        self.alert = (await self.repository.list_alerts())[0]
        settings = replace(Settings(), database_path=self.path, dashboard_token=TOKEN)
        # A stand-in for the Vite build, so these tests do not depend on Node.
        self.assets = Path(self.directory.name) / "dist"
        (self.assets / "assets").mkdir(parents=True)
        (self.assets / "index.html").write_text(INDEX, encoding="utf-8")
        (self.assets / "assets" / "index-abc123.js").write_text("export {};\n")
        (self.assets / "assets" / "index-abc123.py").write_text("print()\n")
        self.dashboard = DashboardServer(settings, self.repository, self.metrics, assets=self.assets)
        self.client = TestClient(TestServer(self.dashboard.application(TOKEN)), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")
        self.headers = {"Origin": self.origin}

    async def asyncTearDown(self):
        await self.client.close()
        await self.dashboard.close()
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    async def login(self):
        response = await self.client.post("/api/login", json={"token": TOKEN}, headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertNotIn(TOKEN, await response.text())
        return response

    async def post(self, path, data):
        return await self.client.post(path, json=data, headers=self.headers)

    async def seed(self, prefix="old"):
        titles = ["ＢＡＢＹＭＥＴＡＬ　ＰＯＳＴＥＲ", "BABYMETAL ポスター フレームのみ",
                  "BABYMETAL poster まとめ売り", "Other band poster"]
        rows = [{"id": f"{prefix}-{index}", "title": title, "price": 5000, "stock": 1}
                for index, title in enumerate(titles)]
        await Ingestion(self.repository, self.metrics, Settings()).check(MemoryProvider(rows), self.alert)
        return await self.repository.list_candidates(alert_id=self.alert["id"])

    async def test_authentication_origin_cookie_and_logout(self):
        response = await self.client.get("/api/alerts")
        self.assertEqual(response.status, 401)
        response = await self.client.post("/api/login", json={"token": TOKEN},
                                          headers={"Origin": "https://other.example"})
        self.assertEqual(response.status, 403)
        response = await self.client.post("/api/login", json={"token": TOKEN})
        self.assertEqual(response.status, 403)
        response = await self.client.post("/api/login", json={"token": TOKEN},
                                          headers={"Origin": self.origin.replace("http:", "https:")})
        self.assertEqual(response.status, 403)
        response = await self.login()
        cookie = response.cookies["dashboard_session"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        response = await self.client.get("/api/alerts")
        self.assertEqual(response.status, 200)
        alert = (await response.json())["alerts"][0]
        self.assertEqual(alert["channel_id"], "9007199254740993")
        self.assertEqual(alert["guild_id"], "9007199254740995")
        response = await self.client.delete("/api/session", headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual((await (await self.client.get("/api/session")).json())["authenticated"], False)
        self.assertEqual((await self.client.get("/api/alerts")).status, 401)

    async def test_login_behind_tls_terminating_proxy(self):
        https_origin = self.origin.replace("http:", "https:")
        # From a peer that is not a trusted proxy the header is ignored, so the https page does not match.
        response = await self.client.post("/api/login", json={"token": TOKEN},
                                          headers={"Origin": https_origin, "X-Forwarded-Proto": "https"})
        self.assertEqual(response.status, 403)
        self.dashboard.settings = replace(self.dashboard.settings, dashboard_trusted_proxies=parse_proxies("127.0.0.1"))
        response = await self.client.post("/api/login", json={"token": TOKEN},
                                          headers={"Origin": https_origin, "X-Forwarded-Proto": "https"})
        self.assertEqual(response.status, 200)
        self.assertTrue(response.cookies["dashboard_session"]["secure"])
        response = await self.client.post("/api/login", json={"token": TOKEN},
                                          headers={"Origin": self.origin, "X-Forwarded-Proto": "https"})
        self.assertEqual(response.status, 403)

    async def test_standalone_preview_matches_live_normalization_and_preserves_original(self):
        await self.login()
        original = "ＢＡＢＹＭＥＴＡＬ　ポスター"
        response = await self.post("/api/preview", {"ruleset": product_rules(), "title": original})
        self.assertEqual(response.status, 200)
        decision = (await response.json())["decision"]
        self.assertEqual(decision["verdict"], "accepted")
        self.assertEqual(decision["normalized_title"], "babymetal ポスター")
        self.assertEqual(original, "ＢＡＢＹＭＥＴＡＬ　ポスター")
        self.assertEqual((await self.repository.list_candidates())["total"], 0)
        self.assertEqual(await self.repository.due_deliveries(), [])

    async def test_replay_feedback_publish_and_live_rejections_share_one_engine(self):
        await self.login()
        saved = await self.seed()
        original_jobs = await self.repository.due_deliveries()
        self.assertEqual(len(original_jobs), 4)
        labels = {"old-0": "relevant", "old-1": "accessory", "old-2": "bundle", "old-3": "wrong_product"}
        for candidate in saved["items"]:
            response = await self.post(f'/api/candidates/{candidate["id"]}/feedback',
                                       {"label": labels[candidate["external_id"]]})
            self.assertEqual(response.status, 200)
        response = await self.post("/api/replay", {"alert_id": self.alert["id"], "ruleset": product_rules()})
        self.assertEqual(response.status, 200)
        replay = await response.json()
        self.assertEqual(replay["summary"]["newly_blocked"], 3)
        self.assertEqual(replay["summary"]["relevant_allowed"], 1)
        self.assertEqual(replay["summary"]["unwanted_blocked"], 3)
        self.assertEqual(replay["summary"]["labeled"], 4)
        self.assertEqual(await self.repository.due_deliveries(), original_jobs)
        self.assertEqual((await self.repository.list_candidates())["total"], 4)
        response = await self.post(f'/api/alerts/{self.alert["id"]}/publish',
                                   {"ruleset": product_rules(), "expected_version_id": None})
        self.assertEqual(response.status, 200)
        version = await response.json()
        self.assertEqual(version["version"], 1)
        self.assertEqual(await self.repository.due_deliveries(), original_jobs)
        saved = await self.seed("new")
        new = [row for row in saved["items"] if row["external_id"].startswith("new")]
        self.assertEqual(sum(row["verdict"] == "accepted" for row in new), 1)
        self.assertEqual(sum(row["verdict"] == "filtered" for row in new), 3)
        self.assertTrue(all(row["ruleset_version_id"] == version["id"] for row in new))
        self.assertEqual(len(await self.repository.due_deliveries()), 5)
        count = await self.repository._call("test_items", lambda: Item.select().count())
        self.assertEqual(count, 5)

    async def test_publish_conflicts_and_rollback_create_new_versions_without_deliveries(self):
        await self.login()
        endpoint = f'/api/alerts/{self.alert["id"]}'
        response = await self.post(endpoint + "/publish", {"ruleset": product_rules(), "expected_version_id": None})
        first = await response.json()
        response = await self.post(endpoint + "/publish", {"ruleset": default_ruleset(), "expected_version_id": None})
        self.assertEqual(response.status, 409)
        response = await self.post(endpoint + "/publish", {"ruleset": default_ruleset(), "expected_version_id": first["id"]})
        second = await response.json()
        response = await self.post(endpoint + "/rollback", {"version_id": first["id"], "expected_version_id": second["id"]})
        self.assertEqual(response.status, 200)
        restored = await response.json()
        self.assertEqual(restored["version"], 3)
        self.assertEqual(restored["restored_from_version_id"], first["id"])
        self.assertEqual(restored["ruleset"], first["ruleset"])
        self.assertEqual(await self.repository.due_deliveries(), [])

    async def test_invalid_requests_never_publish_or_evaluate_unbounded_input(self):
        await self.login()
        response = await self.post("/api/preview", {"title": "x", "ruleset": {"unsupported": True}})
        self.assertEqual(response.status, 400)
        response = await self.post("/api/replay", {"alert_id": self.alert["id"], "ruleset": default_ruleset(), "limit": 501})
        self.assertEqual(response.status, 400)
        response = await self.client.post("/api/preview", data="not-json", headers=self.headers)
        self.assertEqual(response.status, 415)
        response = await self.post(f'/api/alerts/{self.alert["id"]}/publish', {"ruleset": default_ruleset()})
        self.assertEqual(response.status, 400)
        self.assertIsNone((await self.repository.get_review_rules(self.alert["id"]))["active_version"])

    async def test_incomplete_snapshots_and_recorded_blacklists_cannot_become_allowed(self):
        await self.login()
        for kind, payload in (
            ("invalid", {"id": "invalid", "source": "yahooauction", "title": "BABYMETAL poster", "price": None}),
            ("enrichment_error", Listing("unenriched", "surugaya", "BABYMETAL poster", 1, 5000).payload()),
            ("listing", {**Listing("truncated", "mercari", "BABYMETAL poster", 1, 5000).payload(),
                         "archive_truncated": True}),
            ("blacklisted", Listing("blacklisted", "yahooauction", "BABYMETAL poster", 1, 5000).payload()),
        ):
            decision = {"verdict": "filtered" if kind == "blacklisted" else "review", "allowed": False,
                        "normalized_title": "babymetal poster", "normalization_version": 1,
                        "reasons": [], "observation_kind": kind}
            await self.repository.archive_candidate(self.alert, payload, decision)
        response = await self.post("/api/replay", {"alert_id": self.alert["id"], "ruleset": default_ruleset()})
        result = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(result["summary"]["review"], 3)
        self.assertEqual(result["summary"]["filtered"], 1)
        self.assertEqual(result["summary"]["accepted"], 0)
        self.assertEqual(result["summary"]["newly_allowed"], 0)
        self.assertEqual(await self.repository.due_deliveries(), [])

    async def test_login_rate_limit_and_oversized_json_are_bounded(self):
        await self.login()
        response = await self.client.post("/api/preview", data='{broken json',
                                          headers={**self.headers, "Content-Type": "application/json"})
        self.assertEqual(response.status, 400)
        response = await self.post("/api/preview", {"title": "x" * (128 * 1024)})
        self.assertEqual(response.status, 413)
        for _ in range(10):
            response = await self.post("/api/login", {"token": "incorrect"})
            self.assertEqual(response.status, 401)
        response = await self.post("/api/login", {"token": TOKEN})
        self.assertEqual(response.status, 429)
        self.assertEqual((await self.repository.list_candidates())["total"], 0)

    async def test_wrong_keys_lock_out_only_the_visitor_who_sent_them(self):
        self.dashboard.settings = replace(self.dashboard.settings, dashboard_trusted_proxies=parse_proxies("127.0.0.1"))
        guesser, owner = {"X-Forwarded-For": "203.0.113.9"}, {"X-Forwarded-For": "198.51.100.4"}
        for _ in range(10):
            response = await self.client.post("/api/login", json={"token": "wrong-but-long-enough"},
                                              headers={**self.headers, **guesser})
            self.assertEqual(response.status, 401)
        response = await self.client.post("/api/login", json={"token": TOKEN}, headers={**self.headers, **guesser})
        self.assertEqual(response.status, 429)
        response = await self.client.post("/api/login", json={"token": TOKEN}, headers={**self.headers, **owner})
        self.assertEqual(response.status, 200)

    async def test_concurrent_bad_logins_share_the_same_bounded_attempt_window(self):
        original_body = self.dashboard.body
        ready, arrived = asyncio.Event(), 0

        async def simultaneous_bodies(request):
            nonlocal arrived
            data = await original_body(request)
            arrived += 1
            if arrived == 20:
                ready.set()
            await ready.wait()
            return data

        self.dashboard.body = simultaneous_bodies
        responses = await asyncio.wait_for(asyncio.gather(
            *(self.post("/api/login", {"token": "incorrect"}) for _ in range(20))), timeout=5)
        self.assertEqual(sum(response.status == 401 for response in responses), 10)
        self.assertEqual(sum(response.status == 429 for response in responses), 10)
        self.assertEqual(len(self.dashboard.login_failures), 10)

    async def test_static_ui_is_public_but_archive_is_private_and_assets_are_restricted(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("Dashboard", await response.text())
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual((await self.client.get("/assets/index-abc123.js")).status, 200)
        self.assertEqual((await self.client.get("/assets/not-a-file")).status, 404)
        self.assertEqual((await self.client.get("/api/candidates")).status, 401)

    async def test_each_page_view_gets_its_own_style_nonce_and_hashed_assets_are_cached(self):
        pages = [await self.client.get("/") for _ in range(2)]
        nonces = []
        for page in pages:
            policy = page.headers["Content-Security-Policy"]
            nonce = re.search(r"style-src 'self' 'nonce-([A-Za-z0-9_-]+)'", policy).group(1)
            html = await page.text()
            self.assertIn(f'nonce="{nonce}"', html)
            self.assertNotIn(NONCE_PLACEHOLDER, html)
            self.assertIn("script-src 'self';", policy)
            self.assertEqual(page.headers["Cache-Control"], "no-store")
            nonces.append(nonce)
        self.assertNotEqual(*nonces)
        asset = await self.client.get("/assets/index-abc123.js")
        self.assertEqual((asset.status, asset.headers["Content-Type"]), (200, "text/javascript"))
        self.assertEqual(asset.headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(asset.headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("nonce", asset.headers["Content-Security-Policy"])
        for path in ("/assets/index-abc123.py", "/assets/.index-abc123.js", "/assets/%2e%2e%2findex.html",
                     "/assets/..%2Findex.html", "/assets/missing.js", "/index.html"):
            with self.subTest(path=path):
                self.assertEqual((await self.client.get(path)).status, 404)

    async def test_missing_build_returns_a_clear_error_instead_of_a_blank_page(self):
        self.dashboard.assets = Path(self.directory.name) / "not-built"
        response = await self.client.get("/")
        self.assertEqual(response.status, 503)
        self.assertIn("npm run build", await response.text())

    async def test_session_reports_time_left_and_api_errors_use_specific_codes(self):
        self.assertEqual(await (await self.client.get("/api/session")).json(),
                         {"authenticated": False, "method": "access_key", "title": "Dashboard", "bot": None,
                          "bot_running": False})
        self.assertEqual((await (await self.client.get("/api/alerts")).json())["error"], "unauthorized")
        await self.login()
        session = await (await self.client.get("/api/session")).json()
        self.assertTrue(session["authenticated"])
        self.assertGreater(session["expires_in"], 11 * 3600)
        self.assertEqual(session["replay_limit"], 500)
        response = await self.client.get("/api/nothing-here")
        self.assertEqual((response.status, (await response.json())["error"]), (404, "not_found"))
        for path, data in (("/api/preview", {"title": "x", "source": ["not", "text"]}),
                           ("/api/candidates/1/feedback", {"label": {"not": "text"}}),
                           ("/api/candidates/feedback", {"ids": ["1"], "label": ["bundle"]})):
            with self.subTest(path=path):
                response = await self.post(path, data)
                self.assertEqual((response.status, (await response.json())["error"]), (400, "invalid_request"))

    async def test_validate_returns_the_canonical_ruleset_or_the_field_at_fault(self):
        await self.login()
        response = await self.post("/api/rules/validate", {"ruleset": product_rules()})
        self.assertEqual(response.status, 200)
        self.assertEqual([group["id"] for group in (await response.json())["ruleset"]["groups"]],
                         ["subject", "product", "exclude"])
        broken = product_rules()
        broken["groups"][1]["terms"].append({"method": "regex", "value": "("})
        response = await self.post("/api/rules/validate", {"ruleset": broken})
        body = await response.json()
        self.assertEqual((response.status, body["error"], body["field"]), (400, "invalid_request", "groups.1.terms.2"))
        self.assertEqual(body["message"], "Group 2, Term 3: Invalid regular expression")
        response = await self.post("/api/rules/validate", {"ruleset": {**default_ruleset(),
                                                                       "price": {"min": 5, "max": 1}}})
        self.assertEqual((await response.json())["field"], "price")
        self.assertEqual((await self.post("/api/rules/validate", {})).status, 400)

    async def test_candidate_pages_facets_and_bulk_labels_over_http(self):
        await self.login()
        await self.seed()
        params = {"alert_id": self.alert["id"], "limit": "3", "latest": "1", "facets": "1"}
        page = await (await self.client.get("/api/candidates", params=params)).json()
        self.assertEqual((len(page["items"]), page["total"], page["has_more"]), (3, 4, True))
        self.assertEqual(page["facets"]["verdict"], {"accepted": 4, "filtered": 0, "review": 0})
        rest = await (await self.client.get("/api/candidates", params={**params, "cursor": page["next_cursor"]})).json()
        self.assertEqual((len(rest["items"]), rest["has_more"]), (1, False))
        ids = [row["id"] for row in page["items"]]
        response = await self.client.post("/api/candidates/feedback", json={"ids": ids, "label": "bundle"})
        self.assertEqual(response.status, 403)
        response = await self.post("/api/candidates/feedback", {"ids": ids + ["999999"], "label": "bundle"})
        body = await response.json()
        self.assertEqual(([row["id"] for row in body["items"]], body["missing"]), (ids, ["999999"]))
        self.assertEqual({row["feedback"] for row in body["items"]}, {"bundle"})
        for bad in ({"limit": "0"}, {"limit": "abc"}, {"latest": "maybe"}, {"verdict": "nope"}, {"cursor": "bad"},
                    {"source": "ebay"}, {"feedback": "great"}, {"search": "x" * 257}):
            with self.subTest(params=bad):
                self.assertEqual((await self.client.get("/api/candidates", params=bad)).status, 400)

    async def test_alerts_include_counts_and_channel_names_when_the_bot_cache_has_them(self):
        await self.login()
        await self.seed()
        self.dashboard.directory = Names(lambda ids: {channel_id: "posters" for channel_id in ids})
        body = await (await self.client.get("/api/alerts")).json()
        alert = body["alerts"][0]
        self.assertEqual((alert["channel_name"], alert["listing_count"], alert["accepted_count"]), ("posters", 4, 4))
        self.assertEqual(body["totals"], {"archived_count": 4, "unassigned_count": 0, "guilds": {
            "9007199254740995": {"archived_count": 4, "unassigned_count": 0}}})

        def unavailable(ids):
            raise RuntimeError("cache unavailable")
        self.dashboard.directory = Names(unavailable)
        response = await self.client.get("/api/alerts")
        self.assertEqual(response.status, 200)
        self.assertIsNone((await response.json())["alerts"][0]["channel_name"])

    async def test_replay_checks_labeled_listings_outside_the_recent_sample(self):
        await self.login()
        saved = await self.seed()
        labels = {"old-0": "relevant", "old-1": "accessory"}
        for candidate in saved["items"]:
            if candidate["external_id"] in labels:
                await self.post(f'/api/candidates/{candidate["id"]}/feedback', {"label": labels[candidate["external_id"]]})
        response = await self.post("/api/replay", {"alert_id": self.alert["id"], "ruleset": product_rules(), "limit": 1})
        replay = await response.json()
        summary = replay["summary"]
        self.assertEqual((summary["recent"], summary["labeled_extra"], summary["available"], summary["total"]),
                         (1, 2, 4, 3))
        self.assertTrue(summary["truncated"])
        self.assertFalse(summary["budget_exceeded"])
        self.assertEqual((summary["labeled"], summary["relevant_allowed"], summary["unwanted_blocked"]), (2, 1, 1))
        candidate = replay["items"][0]["candidate"]
        self.assertEqual(candidate["external_id"], "old-3")
        self.assertNotIn("payload", candidate)
        self.assertEqual(candidate["price"], 5000)

    async def test_access_key_is_persisted_privately_and_reused(self):
        settings = replace(Settings(), database_path=self.path)
        first = dashboard_key(settings)
        self.assertEqual(dashboard_key(settings), first)
        path = Path(self.path + ".dashboard-token")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertGreaterEqual(len(first), 32)

    async def posted(self):
        """A check without rules posts every seeded listing; each post is recorded as sent, an hour apart."""
        await self.seed()
        now = datetime.now(timezone.utc)
        for index, job in enumerate(await self.repository.due_deliveries()):
            await self.repository.acknowledge_delivery(job["id"], snowflake(now - timedelta(hours=index + 1)))
            await self.repository.complete_delivery(job["id"])
        return await self.repository.removable_posts(self.alert["id"])

    async def test_post_removal_preview_lists_the_posts_the_rules_filter_and_why(self):
        await self.login()
        posts = await self.posted()
        version = await self.repository.publish_review_rules(self.alert["id"], product_rules(), None)
        bundle = next(post for post in posts["posts"] if "まとめ売り" in post["listing"]["title"])
        message = await self.repository.lookup_message(self.alert["channel_id"], bundle["message_id"])
        await self.repository.subscribe(message["item_id"], 77)
        path = f"/api/alerts/{self.alert['id']}/posts/removal-preview"
        response = await self.post(path, {"days": 30})
        self.assertEqual(response.status, 200)
        preview = await response.json()
        self.assertEqual((preview["posts_in_range"], preview["checked"], preview["partial"]), (4, 4, False))
        self.assertEqual(preview["removable_total"], 2)
        self.assertEqual(preview["kept"], {"allowed": 1, "review": 0, "subscribed": 1, "incomplete": 0,
                                           "unchecked": 0, "queued": 0})
        self.assertEqual({entry["key"]: entry["count"] for entry in preview["reasons"]},
                         {"excluded_group_match:exclude": 1, "required_group_missing:subject": 1})
        self.assertEqual({post["title"] for post in preview["posts"]},
                         {"BABYMETAL ポスター フレームのみ", "Other band poster"})
        # Discord IDs do not fit in a JavaScript number, so they travel as text.
        self.assertTrue(all(isinstance(post["message_id"], str) for post in preview["posts"]))
        self.assertEqual((preview["active_version_id"], preview["guild_id"]), (version["id"], "9007199254740995"))
        self.assertFalse(preview["bot_running"])
        response = await self.post(path, {"days": None, "ruleset": default_ruleset()})
        self.assertEqual((await response.json())["removable_total"], 0)
        response = await self.post(path, {"days": 14})
        self.assertEqual((response.status, (await response.json())["error"]), (400, "invalid_request"))

    async def test_post_removal_queues_checked_posts_and_reports_progress(self):
        await self.login()
        posts = await self.posted()
        version = await self.repository.publish_review_rules(self.alert["id"], product_rules(), None)
        path = f"/api/alerts/{self.alert['id']}/posts/removal"
        ids = [str(post["message_id"]) for post in posts["posts"]]
        # One of the four is allowed by the rules, so it is checked again and skipped.
        response = await self.post(path, {"version_id": version["id"], "message_ids": ids})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"queued": 3, "skipped": 1, "bot_running": False})
        status = await (await self.client.get(path)).json()
        self.assertEqual((status["run"]["total"], status["run"]["pending"], status["run"]["removed"]), (3, 3, 0))
        self.assertEqual({job["kind"] for job in await self.repository.due_deliveries()}, {"delete"})
        for body in ({"version_id": version["id"], "message_ids": []},
                     {"version_id": version["id"], "message_ids": ids * 300},
                     {"version_id": version["id"], "message_ids": ["not-a-number"]}):
            self.assertEqual((await self.post(path, body)).status, 400)
        # Rules published after the preview: the posts have to be checked again.
        await self.repository.publish_review_rules(self.alert["id"], default_ruleset(), version["id"])
        response = await self.post(path, {"version_id": version["id"], "message_ids": ids})
        self.assertEqual((response.status, (await response.json())["error"]), (409, "version_conflict"))
