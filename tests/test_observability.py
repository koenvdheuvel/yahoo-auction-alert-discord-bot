import asyncio
from dataclasses import replace
import json
import logging
import time

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from aiohttp import web
from prometheus_client.parser import text_string_to_metric_families

from config import Settings
from observability import Health, JsonFormatter, Metrics, MonitoringServer, log_context


def test_json_logging_correlates_context_and_redacts_secrets_and_exception():
    secret = "sample-secret-value"
    formatter = JsonFormatter(secrets=(secret,))
    context = log_context.set({"cycle_id": "cycle", "alert_id": 123, "source": "mercari"})
    try:
        try:
            raise ValueError("Error involving " + secret)
        except ValueError as error:
            record = logging.LogRecord("provider", logging.ERROR, __file__, 1,
                                       "failed using %s", (secret,), (type(error), error, error.__traceback__))
        record.fields = {"nested": {"authorization": "Bot hidden", "value": secret}}
        encoded = formatter.format(record)
        payload = json.loads(encoded)
        assert secret not in encoded
        assert "Bot hidden" not in encoded
        assert payload["cycle_id"] == "cycle"
        assert payload["alert_id"] == 123
        assert payload["source"] == "mercari"
        assert payload["level"] == "ERROR"
        assert "ValueError" in payload["exception"]
        assert payload["nested"]["authorization"] == "[redacted]"
    finally:
        log_context.reset(context)
    assert not log_context.get()


def test_health_readiness_tracks_staleness_worker_failure_and_shutdown():
    async def scenario():
        task = asyncio.create_task(asyncio.sleep(60))
        health = Health(max_poll_age=10, connected=True, repository_available=True, tasks={"poller": task})
        try:
            assert health.status()[0]
            health.last_poll = time.monotonic() - 11
            assert not health.status()[0]
            health.last_poll = time.monotonic()
            assert health.status()[0]
            health.last_stats = time.monotonic() - 31
            assert not health.status()[0]
            health.last_stats = time.monotonic()
            health.failed_worker = "poller"
            assert not health.status()[0]
            health.failed_worker = None
            health.stopping = True
            assert not health.status()[0]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        health.stopping = False
        assert not health.status()[0]

    asyncio.run(scenario())


def test_metrics_and_live_and_ready_routes_have_independent_status():
    async def scenario():
        metrics, health = Metrics(), Health(max_poll_age=60)
        monitor = MonitoringServer(Settings(), metrics, health)
        # Use aiohttp's local test listener without binding the configured port.
        app = web.Application()
        app.router.add_get("/metrics", monitor.scrape)
        app.router.add_get("/health/live", monitor.live)
        app.router.add_get("/health/ready", monitor.ready)
        server = TestServer(app)
        await server.start_server()
        try:
            async with ClientSession() as client:
                async with client.get(server.make_url("/health/live")) as response:
                    assert response.status == 200
                    assert await response.json() == {"live": True}
                async with client.get(server.make_url("/health/ready")) as response:
                    assert response.status == 503
                    assert not (await response.json())["ready"]
                async with client.get(server.make_url("/metrics")) as response:
                    assert response.status == 200
                    assert response.headers["Content-Type"].startswith("text/plain")
                    scrape = await response.text()
                    families = list(text_string_to_metric_families(scrape))
                    assert any(family.name == "auction_bot_polls" for family in families)
                    assert "auction_bot_reaction_errors_total 0.0" in scrape
                task = asyncio.create_task(asyncio.sleep(60))
                health.tasks = {"poller": task}
                health.connected = health.repository_available = True
                try:
                    async with client.get(server.make_url("/health/ready")) as response:
                        assert response.status == 200
                        assert (await response.json())["ready"]
                    health.stopping = True
                    async with client.get(server.make_url("/health/live")) as response:
                        assert response.status == 503
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            await server.close()

    asyncio.run(scenario())


def test_monitoring_can_be_disabled_without_affecting_health():
    async def scenario():
        monitor = MonitoringServer(replace(Settings(), monitoring_enabled=False), Metrics(), Health(60))
        await monitor.start()
        assert monitor.runner is None
        await monitor.close()

    asyncio.run(scenario())


def test_global_metric_labels_contain_no_alert_item_channel_query_or_user_dimensions():
    metrics = Metrics()
    metrics.checks.labels("surugaya", "success").inc()
    metrics.requests.labels("surugaya", "detail", "success").inc()
    labels = {name for family in metrics.registry.collect()
              for sample in family.samples for name in sample.labels}
    assert not labels.intersection({"alert_id", "item_id", "listing_id", "channel_id", "guild_id", "query", "search_query", "user_id", "message_id"})


def test_alert_metadata_resolves_names_without_putting_text_on_check_metrics():
    from prometheus_client import generate_latest

    metrics = Metrics()
    name = '日本のグッズ "rare"\nedition'
    metrics.update_alert_metadata([{"id": 17, "channel_id": 123, "search_query": name}])
    metrics.observe_check(17, "mercari", "error", .25)
    families = list(text_string_to_metric_families(generate_latest(metrics.registry).decode()))
    info = next(sample for family in families for sample in family.samples
                if sample.name == "auction_bot_alert_info")
    assert info.labels == {"alert_id": "17", "search_query": name, "channel_id": "123"}
    assert info.value == 1
    counts = [sample for family in families for sample in family.samples
              if sample.name == "auction_bot_alert_checks_total"]
    assert len(counts) == 1
    assert counts[0].labels == {"alert_id": "17", "source": "mercari", "outcome": "error"}
    assert counts[0].value == 1


def test_retired_alert_metrics_are_removed_and_late_checks_do_not_recreate_them():
    metrics = Metrics()
    metrics.update_alert_metadata([{"id": 17, "channel_id": 123, "search_query": "figure"}])
    metrics.observe_check(17, "mercari", "success", .1)
    metrics.update_alert_metadata([])
    metrics.observe_check(17, "mercari", "success", .1)
    samples = [sample for family in metrics.registry.collect() for sample in family.samples]
    assert not any(sample.labels.get("alert_id") == "17" for sample in samples)
    assert metrics.registry.get_sample_value("auction_bot_checks_total", {
        "source": "mercari", "outcome": "success"}) == 2


def test_reused_alert_id_replaces_metadata_and_resets_its_check_history():
    metrics = Metrics()
    metrics.update_alert_metadata([{"id": 17, "channel_id": 123, "search_query": "old"}])
    metrics.observe_check(17, "mercari", "success", .1)
    metrics.update_alert_metadata([{"id": 17, "channel_id": 456, "search_query": "new"}])
    metrics.observe_check(17, "mercari", "error", .2)
    samples = [sample for family in metrics.registry.collect() for sample in family.samples]
    info = [sample for sample in samples if sample.name == "auction_bot_alert_info"]
    assert len(info) == 1
    assert info[0].labels == {"alert_id": "17", "channel_id": "456", "search_query": "new"}
    assert metrics.registry.get_sample_value("auction_bot_alert_checks_total", {
        "alert_id": "17", "source": "mercari", "outcome": "success"}) is None


def test_late_result_for_replaced_identity_is_not_attributed_to_new_alert():
    metrics = Metrics()
    metrics.update_alert_metadata([{"id": 17, "channel_id": 123, "search_query": "old"}])
    metrics.begin_check(17, "mercari", ("old", "123"))
    metrics.update_alert_metadata([{"id": 17, "channel_id": 456, "search_query": "new"}])
    metrics.observe_check(17, "mercari", "error", .2, ("old", "123"))
    assert metrics.registry.get_sample_value("auction_bot_alert_checks_total", {
        "alert_id": "17", "source": "mercari", "outcome": "error"}) is None
    assert metrics.registry.get_sample_value("auction_bot_checks_total", {
        "source": "mercari", "outcome": "error"}) == 1
