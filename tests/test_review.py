"""Real review HTTP flows, live ingestion and replay isolation on temporary SQLite."""
from dataclasses import replace
import asyncio
from pathlib import Path
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
from review import ReviewServer, review_key
from storechecker import Ingestion


TOKEN = "filter-lab-test-access-key-123456789"


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

    async def enrich(self, listing):
        return listing


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "review.db")
        configure_database(self.path)
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(9007199254740993, "BABYMETAL posters", guild_id=9007199254740995)
        self.alert = (await self.repository.list_alerts())[0]
        settings = replace(Settings(), database_path=self.path, review_token=TOKEN)
        self.review = ReviewServer(settings, self.repository, self.metrics)
        self.client = TestClient(TestServer(self.review.application(TOKEN)), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")
        self.headers = {"Origin": self.origin}

    async def asyncTearDown(self):
        await self.client.close()
        await self.review.close()
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
        cookie = response.cookies["filter_lab_session"]
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

    async def test_concurrent_bad_logins_share_the_same_bounded_attempt_window(self):
        original_body = self.review.body
        ready, arrived = asyncio.Event(), 0

        async def simultaneous_bodies(request):
            nonlocal arrived
            data = await original_body(request)
            arrived += 1
            if arrived == 20:
                ready.set()
            await ready.wait()
            return data

        self.review.body = simultaneous_bodies
        responses = await asyncio.wait_for(asyncio.gather(
            *(self.post("/api/login", {"token": "incorrect"}) for _ in range(20))), timeout=5)
        self.assertEqual(sum(response.status == 401 for response in responses), 10)
        self.assertEqual(sum(response.status == 429 for response in responses), 10)
        self.assertEqual(len(self.review.login_failures), 10)

    async def test_static_ui_is_public_but_archive_is_private_and_assets_are_restricted(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("Filter Lab", await response.text())
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual((await self.client.get("/assets/app.js")).status, 200)
        self.assertEqual((await self.client.get("/assets/not-a-file")).status, 404)
        self.assertEqual((await self.client.get("/api/candidates")).status, 401)

    async def test_access_key_is_persisted_privately_and_reused(self):
        settings = replace(Settings(), database_path=self.path)
        first = review_key(settings)
        self.assertEqual(review_key(settings), first)
        path = Path(self.path + ".review-token")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertGreaterEqual(len(first), 32)
