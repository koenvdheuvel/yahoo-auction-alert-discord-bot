"""The Status page's graphs: the Grafana dashboard's panels, run against a local fake Prometheus."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from config import Settings
from dashboard import DashboardServer
from dashboard_graphs import DASHBOARD, PANELS, load_panels
from models import configure_database, create_tables, database
from observability import Metrics
from repositories import Repository

TOKEN = "dashboard-test-access-key-123456789"
GUILD_A, GUILD_B = 1100000000000000001, 1100000000000000002
INDEX = '<!doctype html><html><head><title>Dashboard</title></head><body><div id="root"></div></body></html>'
# Panels whose series are about single searches.
PER_SEARCH = (19, 20)


class FakePrometheus:
    """Prometheus' query API. Every query answers the bot's series; one that keeps alert_id answers
    a series per search and marketplace instead."""

    def __init__(self):
        self.queries = []
        self.instances = ["bot:9100"]
        # (alert_id, search_query) per search Prometheus has series for.
        self.searches = []
        # The marketplaces each of those searches has series for.
        self.sources = ["yahooauction"]
        # Prometheus cannot run the queries that contain this.
        self.broken = ""
        self.server = TestServer(self.application(), host="127.0.0.1")

    def application(self):
        application = web.Application()
        application.router.add_post("/api/v1/query", self.query)
        application.router.add_post("/api/v1/query_range", self.query)
        return application

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.port}"

    async def query(self, request):
        form = dict(await request.post())
        self.queries.append(form)
        if self.broken and self.broken in form["query"]:
            return web.json_response({"status": "error", "errorType": "bad_data",
                                      "error": "1:7: parse error: unexpected identifier"}, status=400)
        if "alert_id" in form["query"]:
            labels = [{"alert_id": str(alert_id), "search_query": query, "source": source}
                      for alert_id, query in self.searches for source in self.sources]
        else:
            # The last one names a search without its alert_id, which no server may see.
            labels = [{"source": "yahooauction", "outcome": "success"}, {"search_query": "Someone's search"}]
        result = []
        for instance in self.instances:
            for index, names in enumerate(labels):
                metric = {"__name__": "auction_bot_checks_total", "job": "auction-bot", "instance": instance, **names}
                if "step" in form:
                    start, step = int(form["start"]), int(form["step"])
                    values = [[start, "1"], [start + step, "NaN"], [start + 2 * step, "3"]]
                    result.append({"metric": metric, "values": values})
                else:
                    result.append({"metric": metric, "value": [int(form["time"]), str(index + 3)]})
        kind = "matrix" if "step" in form else "vector"
        return web.json_response({"status": "success", "data": {"resultType": kind, "result": result}})


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "alerts.db")
        configure_database(self.path)
        create_tables()
        self.metrics = Metrics()
        self.repository = Repository(self.metrics)
        await self.repository.start()
        await self.repository.register_alert(41, "BABYMETAL poster", guild_id=GUILD_A)
        await self.repository.register_alert(51, "Vinyl", guild_id=GUILD_B)
        alerts = {alert["search_query"]: alert["id"] for alert in await self.repository.list_alerts()}
        self.prometheus = FakePrometheus()
        # Alert A's ID once named a search that was deleted since; it must not show as alert A.
        self.prometheus.searches = [(alerts["BABYMETAL poster"], "BABYMETAL poster"), (alerts["Vinyl"], "Vinyl"),
                                    (alerts["BABYMETAL poster"], "Deleted search")]
        await self.prometheus.server.start_server()
        self.dashboard = self.client = None

    async def asyncTearDown(self):
        if self.client is not None:
            await self.client.close()
            await self.dashboard.close()
        await self.prometheus.server.close()
        await self.repository.close()
        database.close()
        self.directory.cleanup()

    async def start(self, **settings):
        """The dashboard with these settings, signed in with the access key."""
        settings = replace(Settings(), database_path=self.path, dashboard_token=TOKEN,
                           **{"prometheus_url": self.prometheus.url, **settings})
        assets = Path(self.directory.name) / "dist"
        assets.mkdir(exist_ok=True)
        (assets / "index.html").write_text(INDEX, encoding="utf-8")
        self.dashboard = DashboardServer(settings, self.repository, self.metrics, assets=assets)
        self.client = TestClient(TestServer(self.dashboard.application(TOKEN)), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        origin = str(self.client.make_url("/")).rstrip("/")
        response = await self.client.post("/api/login", json={"token": TOKEN}, headers={"Origin": origin})
        self.assertEqual(response.status, 200)

    async def graphs(self, guild_id=GUILD_A, **params):
        response = await self.client.get(f"/api/guilds/{guild_id}/graphs", params=params)
        self.assertEqual(response.status, 200, await response.text())
        body = await response.json()
        return body, {panel["id"]: panel for section in body["sections"] for panel in section["panels"]}

    async def test_each_server_sees_the_whole_bot_and_only_its_own_searches(self):
        await self.start()
        body, panels = await self.graphs()
        self.assertEqual(list(panels), list(PANELS))
        self.assertEqual([section["title"] for section in body["sections"]],
                         list(dict.fromkeys(panel.section for panel in load_panels())))
        self.assertIsNone(body["warning"])
        searches = panels[19]["rows"]
        self.assertEqual([(row["labels"]["search_query"], row["value"]) for row in searches],
                         [("BABYMETAL poster", 3)])
        self.assertEqual([series["labels"]["search_query"] for series in panels[20]["series"]], ["BABYMETAL poster"])
        # The bot's own series, without the search that has no alert_id and without the labels
        # every series of one bot shares.
        self.assertEqual([series["labels"] for series in panels[14]["series"]],
                         [{"outcome": "success", "source": "yahooauction"}])
        _, panels = await self.graphs(GUILD_B)
        self.assertEqual([row["labels"]["search_query"] for row in panels[19]["rows"]], ["Vinyl"])
        self.assertEqual(len(panels[14]["series"]), 1)
        # Both servers' pages came from one round of queries.
        self.assertEqual(len(self.prometheus.queries), sum(len(panel.targets) for panel in load_panels()))

    async def test_searches_with_the_same_text_keep_their_rows_together(self):
        await self.repository.register_alert(42, "BABYMETAL poster", guild_id=GUILD_A)
        first, second = sorted(str(alert["id"]) for alert in await self.repository.list_alerts()
                               if alert["search_query"] == "BABYMETAL poster")
        self.prometheus.searches = [(first, "BABYMETAL poster"), (second, "BABYMETAL poster")]
        self.prometheus.sources = ["yahooauction", "mercari"]
        await self.start()
        _, panels = await self.graphs()
        self.assertEqual([(row["labels"]["alert_id"], row["labels"]["source"]) for row in panels[19]["rows"]],
                         [(first, "mercari"), (first, "yahooauction"), (second, "mercari"), (second, "yahooauction")])

    async def test_queries_fill_in_grafanas_variables_and_values_line_up_with_the_times(self):
        await self.start(prometheus_instance="bot.example:9100")
        self.prometheus.instances = ["bot.example:9100"]
        body, panels = await self.graphs(range="1h")
        self.assertEqual((body["step"], body["end"] - body["start"]), (30, 3600))
        self.assertEqual(body["times"], list(range(body["start"], body["end"] + 1, 30)))
        for form in self.prometheus.queries:
            self.assertNotIn("$", form["query"])
            self.assertIn('instance=~"bot\\\\.example:9100"', form["query"])
            if "step" in form:
                self.assertEqual((form["start"], form["end"], form["step"]),
                                 (str(body["start"]), str(body["end"]), "30"))
            else:
                self.assertEqual(form["time"], str(body["end"]))
                self.assertIn("[3600s]", form["query"])
        # Grafana's $__rate_interval: the step plus a scrape, and at least four scrapes.
        rated = sum("$__rate_interval" in target.expr for panel in load_panels() for target in panel.targets)
        self.assertGreater(rated, 0)
        self.assertEqual(sum("[60s]" in form["query"] for form in self.prometheus.queries), rated)
        # A sample Prometheus has no number for is a gap.
        self.assertEqual(panels[14]["series"][0]["values"][:4], [1, None, 3, None])
        self.assertEqual(len(panels[14]["series"][0]["values"]), len(body["times"]))
        self.prometheus.queries.clear()
        body, _ = await self.graphs(range="24h")
        self.assertEqual(body["step"], 720)
        self.assertEqual(sum("[735s]" in form["query"] for form in self.prometheus.queries), rated)

    async def test_several_bots_leave_out_the_graphs_about_single_searches(self):
        await self.start()
        self.prometheus.instances = ["bot-a:9100", "bot-b:9100"]
        body, panels = await self.graphs()
        self.assertIn("PROMETHEUS_INSTANCE", body["warning"])
        for panel_id in PER_SEARCH:
            self.assertTrue(panels[panel_id]["error"])
            self.assertEqual(panels[panel_id].get("rows", panels[panel_id].get("series")), [])
        self.assertEqual(len(panels[14]["series"]), 2)

    async def test_a_query_prometheus_cannot_run_fails_only_its_own_panel(self):
        await self.start()
        self.prometheus.broken = "source_last_success"
        _, panels = await self.graphs()
        self.assertIn("parse error", panels[15]["error"])
        self.assertEqual(panels[15]["series"], [])
        self.assertEqual([panel_id for panel_id, panel in panels.items() if panel["error"]], [15])
        # Without Prometheus every panel says so, and the page itself still loads.
        await self.prometheus.server.close()
        _, panels = await self.graphs(range="6h")
        self.assertEqual({panel["error"] for panel in panels.values()}, {"Prometheus did not answer."})

    async def test_only_the_offered_ranges_are_accepted(self):
        await self.start()
        response = await self.client.get(f"/api/guilds/{GUILD_A}/graphs", params={"range": "30d"})
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "invalid_request")
        self.assertEqual(self.prometheus.queries, [])

    async def test_without_prometheus_there_are_no_graphs(self):
        await self.start(prometheus_url="")
        body, panels = await self.graphs()
        self.assertEqual((body["enabled"], panels), (False, {}))
        self.assertEqual(self.prometheus.queries, [])


def test_every_grafana_panel_explains_its_graph():
    panels = json.loads(DASHBOARD.read_text(encoding="utf-8"))["panels"]
    panels += [child for row in panels for child in row.get("panels", [])]
    assert [panel["title"] for panel in panels if panel["type"] != "row" and not panel.get("description", "").strip()] == []
    assert [panel.id for panel in load_panels()] == list(PANELS)


def test_a_dashboard_change_the_status_page_cannot_draw_stops_startup(tmp_path):
    def dashboard(**changes):
        panel = {"id": 1, "type": "timeseries", "title": "Checks", "datasource": {"type": "prometheus"},
                 "targets": [{"expr": 'sum(rate(checks{instance=~"$instance"}[$__rate_interval]))', "range": True}]}
        path = tmp_path / "dashboard.json"
        # A collapsed row keeps its panels inside it.
        path.write_text(json.dumps({"panels": [{"type": "row", "title": "Polling", "panels": [panel | changes]}]}))
        return path

    assert [(panel.id, panel.section) for panel in load_panels(dashboard(), ids=(1,))] == [(1, "Polling")]
    for changes, message in (
        ({"type": "stat"}, "stat panel"),
        ({"datasource": {"type": "loki"}}, "does not query Prometheus"),
        ({"targets": [{"expr": 'checks{source=~"$source"}', "range": True}]}, r"\$source"),
        ({"type": "table"}, "needs instant queries"),
    ):
        with pytest.raises(ValueError, match=message):
            load_panels(dashboard(**changes), ids=(1,))
    with pytest.raises(ValueError, match="no panel 2"):
        load_panels(dashboard(), ids=(2,))


def test_prometheus_settings_are_checked_at_startup(monkeypatch):
    for name in ("DASHBOARD_TOKEN", "DASHBOARD_TOKEN_FILE", "DASHBOARD_PUBLIC_URL", "DASHBOARD_DISCORD_CLIENT_SECRET",
                 "DASHBOARD_DISCORD_CLIENT_SECRET_FILE", "PROMETHEUS_URL", "PROMETHEUS_INSTANCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "token")
    assert (Settings.from_env().prometheus_url, Settings.from_env().prometheus_instance) == ("", "")
    monkeypatch.setenv("PROMETHEUS_URL", "https://metrics.example.com:9443/prometheus/")
    monkeypatch.setenv("PROMETHEUS_INSTANCE", "[2001:db8::1]:9100")
    settings = Settings.from_env()
    assert (settings.prometheus_url, settings.prometheus_instance) == (
        "https://metrics.example.com:9443/prometheus", "[2001:db8::1]:9100")
    monkeypatch.delenv("PROMETHEUS_INSTANCE")
    for url, message in (
        ("prometheus:9090", "must start with http"),
        ("http://prometheus:99999", "invalid port"),
        ("http://admin:secret@prometheus:9090", "without a user name"),
        ("http://prometheus:9090/?timeout=5s", "without a user name, password or query"),
    ):
        monkeypatch.setenv("PROMETHEUS_URL", url)
        with pytest.raises(ValueError, match=message):
            Settings.from_env()
    monkeypatch.setenv("PROMETHEUS_URL", "http://prometheus:9090")
    monkeypatch.setenv("PROMETHEUS_INSTANCE", 'bot"} or vector(1) #')
    with pytest.raises(ValueError, match="must be an instance label"):
        Settings.from_env()
    monkeypatch.delenv("PROMETHEUS_URL")
    monkeypatch.setenv("PROMETHEUS_INSTANCE", "bot:9100")
    with pytest.raises(ValueError, match="also set PROMETHEUS_URL"):
        Settings.from_env()
