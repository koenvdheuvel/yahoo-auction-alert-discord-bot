"""Offline scheduler and composition guarantees, independent of real providers."""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import Settings
from observability import Metrics
from runtime import Runtime


class Resource:
    def __init__(self):
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True


class Repository(Resource):
    def __init__(self, alerts=None):
        super().__init__()
        self.alerts = alerts or []

    async def list_alerts(self):
        return self.alerts

    async def stats(self):
        return {"alerts": len(self.alerts), "pending": 0, "failed": 0,
                "oldest_pending_age": 0, "disabled_legacy_filters": 0,
                "alert_metadata": self.alerts}


class Bot:
    def __init__(self):
        self.closed = asyncio.Event()
        self.runtime = None

    async def close(self):
        await self.runtime.close()
        self.closed.set()


class Delivery:
    async def run(self):
        await asyncio.Future()


def build_runtime(check, alerts=None, settings=None, delivery=None):
    settings = settings or replace(Settings(), monitoring_enabled=False, dashboard_enabled=False)
    bot = Bot()
    repo, http, metrics = Repository(alerts), Resource(), Metrics()
    runtime = Runtime(bot, settings, repo, http, SimpleNamespace(check=check),
                      delivery or Delivery(), {"yahooauction": object()}, metrics)
    bot.runtime = runtime
    return runtime


def alert(identifier, query="query"):
    return {"id": identifier, "channel_id": 10, "guild_id": 20, "search_query": query}


def value(runtime, name, labels=None):
    return runtime.metrics.registry.get_sample_value("auction_bot_" + name, labels or {})


def test_import_has_no_token_database_or_bot_side_effects(tmp_path):
    env = dict(os.environ)
    env.pop("BOT_TOKEN", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["DATABASE_URL"] = str(tmp_path / "must-not-exist.db")
    result = subprocess.run([sys.executable, "-c", "import main; assert not hasattr(main, 'bot')"],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_factory_registers_commands_without_starting_network_or_workers(tmp_path, monkeypatch):
    import main
    import observability

    # Preserve pytest's capture handlers while testing composition.
    monkeypatch.setattr(observability, "configure_logging", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)
    database_path = tmp_path / "configured.db"
    settings = replace(Settings(), token="MTIzNDU2Nzg5.MOCK.MOCK", database_path=str(database_path),
                       monitoring_enabled=False, dashboard_enabled=False)
    bot = main.create_application(settings)
    assert database_path.exists()
    assert not bot.services.runtime.tasks
    assert bot.services.runtime.http.session is None
    assert set(bot.services.runtime.providers) == set(settings.enabled_sources)
    import hikari
    import lightbulb

    assert isinstance(bot, hikari.GatewayBot)
    assert isinstance(bot.services.commands, lightbulb.Client)
    names = {command.name if isinstance(command, lightbulb.Group) else command._command_data.name
             for command in bot.services.commands.registered_commands}
    assert names == {"alerts", "allalerts", "register", "unregister",
                     "filters", "cleanup", "reacttocleanup"}
    asyncio.run(bot.services.runtime.close())


def test_failed_runtime_returns_nonzero_process_status(monkeypatch):
    import main

    bot = SimpleNamespace(services=SimpleNamespace(runtime=SimpleNamespace(failure=RuntimeError("failed"))),
                          run=lambda **kwargs: None)
    monkeypatch.setattr(main, "create_application", lambda: bot)
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 1


def test_factory_gateway_events_open_resources_before_starting_workers(tmp_path, monkeypatch):
    import hikari
    import lightbulb
    import main
    import observability

    monkeypatch.setattr(observability, "configure_logging", lambda *args, **kwargs: None)
    synced = AsyncMock()
    monkeypatch.setattr(lightbulb.Client, "sync_application_commands", synced)
    original_stop = lightbulb.Client.stop
    stopped_before_runtime = []

    async def stop_client(client, *args):
        stopped_before_runtime.append(not bot.services.runtime.health.stopping)
        await original_stop(client, *args)

    monkeypatch.setattr(lightbulb.Client, "stop", stop_client)

    async def scenario():
        nonlocal bot
        bot = main.create_application(replace(Settings(), token="MTIzNDU2Nzg5.MOCK.MOCK",
                                               database_path=str(tmp_path / "db"), monitoring_enabled=False, dashboard_enabled=False))

        def listener(event_type, name):
            return next(callback for callback in bot.get_listeners(event_type) if callback.__name__ == name)

        try:
            await listener(hikari.StartingEvent, "on_starting")(None)
            assert bot.services.runtime.http.session is not None
            assert not bot.services.runtime.tasks
            synced.assert_not_awaited()
            reconcile = AsyncMock()
            bot.services.repository.reconcile_guilds = reconcile
            await listener(hikari.StartedEvent, "on_started")(None)
            synced.assert_awaited_once()
            # Channels arrive after StartedEvent, so servers are filled in per server instead.
            reconcile.assert_not_awaited()
            assert set(bot.services.runtime.tasks) == {"poller", "delivery", "event_loop", "database_stats"}
            await listener(hikari.StoppingEvent, "on_stopping")(None)
            assert stopped_before_runtime == [True]
            assert all(task.done() for task in bot.services.runtime.tasks.values())
            assert bot.services.runtime.http.session is None
        finally:
            await bot.services.commands.stop()
            await bot.services.runtime.close()

    bot = None
    asyncio.run(scenario())


def test_server_channels_and_threads_fill_in_missing_alert_servers(tmp_path, monkeypatch, caplog):
    import hikari
    import main
    import observability

    monkeypatch.setattr(observability, "configure_logging", lambda *args, **kwargs: None)

    async def scenario():
        bot = main.create_application(replace(Settings(), token="MTIzNDU2Nzg5.MOCK.MOCK",
                                               database_path=str(tmp_path / "db"), monitoring_enabled=False,
                                               dashboard_enabled=False))
        try:
            listeners = [callback for event_type in (hikari.GuildAvailableEvent, hikari.GuildJoinEvent)
                         for callback in bot.get_listeners(event_type) if callback.__name__ == "on_guild_available"]
            assert len(listeners) == 2
            reconcile = AsyncMock(return_value=1)
            bot.services.repository.reconcile_guilds = reconcile
            event = SimpleNamespace(guild_id=hikari.Snowflake(5), channels={hikari.Snowflake(11): None},
                                    threads={hikari.Snowflake(12): None})
            await listeners[0](event)
            reconcile.assert_awaited_once_with({11: 5, 12: 5})
            # A failure is logged and does not reach the gateway's event loop.
            reconcile.side_effect = RuntimeError("Repository is closed")
            await listeners[1](event)
            assert "guild_reconcile_failed" in caplog.text
        finally:
            await bot.services.commands.stop()
            await bot.services.runtime.close()

    asyncio.run(scenario())


def test_command_sync_failure_stops_startup_before_background_work(tmp_path, monkeypatch, caplog):
    import hikari
    import lightbulb
    import main
    import observability

    monkeypatch.setattr(observability, "configure_logging", lambda *args, **kwargs: None)
    synced = AsyncMock(side_effect=RuntimeError("command sync failed"))
    monkeypatch.setattr(lightbulb.Client, "sync_application_commands", synced)
    closed = []

    async def close_bot(bot):
        closed.append(bot)

    monkeypatch.setattr(main.ApplicationBot, "close", close_bot)

    async def scenario():
        bot = main.create_application(replace(Settings(), token="MTIzNDU2Nzg5.MOCK.MOCK",
                                               database_path=str(tmp_path / "db"), monitoring_enabled=False, dashboard_enabled=False))

        def listener(event_type, name):
            return next(callback for callback in bot.get_listeners(event_type) if callback.__name__ == name)

        try:
            await listener(hikari.StartingEvent, "on_starting")(None)
            reconcile = AsyncMock()
            bot.services.repository.reconcile_guilds = reconcile
            await listener(hikari.StartedEvent, "on_started")(None)
            synced.assert_awaited_once()
            reconcile.assert_not_awaited()
            assert closed == [bot]
            assert not bot.services.runtime.tasks
            assert isinstance(bot.services.runtime.failure, RuntimeError)
            assert bot.services.runtime.health.failed_worker == "startup"
            assert not bot.services.runtime.health.status()[0]
            assert "command sync failed" in caplog.text
            await listener(hikari.StoppingEvent, "on_stopping")(None)
            assert bot.services.runtime.http.session is None
            assert bot.services.repository.closed
        finally:
            await bot.services.commands.stop()
            await bot.services.runtime.close()

    asyncio.run(scenario())


def test_command_error_handler_responds_privately_and_logs_unexpected_errors(tmp_path, monkeypatch, caplog):
    import hikari
    import lightbulb
    import main
    import observability
    from commands.base import GuildOnlyError

    monkeypatch.setattr(observability, "configure_logging", lambda *args, **kwargs: None)

    async def scenario():
        bot = main.create_application(replace(Settings(), token="MTIzNDU2Nzg5.MOCK.MOCK",
                                               database_path=str(tmp_path / "db"), monitoring_enabled=False, dashboard_enabled=False))
        client = bot.services.commands
        handler = next(callback for callbacks in client._error_handlers.values() for callback in callbacks)
        context = SimpleNamespace(channel_id=123, respond=AsyncMock(),
                                  command_data=SimpleNamespace(qualified_name="register"))

        def failure(invocation=None, hooks=()):
            return lightbulb.exceptions.ExecutionPipelineFailedException(
                [(SimpleNamespace(name="test_hook"), cause) for cause in hooks], invocation,
                SimpleNamespace(), context)

        try:
            permission = lightbulb.prefab.MissingRequiredPermission(
                hikari.Permissions.MANAGE_CHANNELS, hikari.Permissions.NONE)
            assert await handler(failure(hooks=(permission,))) is True
            assert context.respond.await_args.kwargs["ephemeral"] is True
            assert "permission" in context.respond.await_args.args[0]
            assert await handler(failure(hooks=(GuildOnlyError(),))) is True
            assert "permission" in context.respond.await_args.args[0]
            error = ValueError("database command failed")
            assert await handler(failure(error)) is True
            assert context.respond.await_args.kwargs["ephemeral"] is True
            assert "database command failed" not in context.respond.await_args.args[0]
            assert "command_failed" in caplog.text
            assert "database command failed" in caplog.text
            # Mixed hook failures include a permission denial, but must still
            # expose every unexpected cause through logs and the error metric.
            mixed = RuntimeError("unexpected permission hook failure")
            caplog.clear()
            assert await handler(failure(hooks=(permission, mixed))) is True
            assert "The command failed" in context.respond.await_args.args[0]
            assert "unexpected permission hook failure" in caplog.text
            assert "MissingRequiredPermission" in caplog.text
            metrics = bot.services.metrics.registry
            assert metrics.get_sample_value("auction_bot_command_errors_total", {"outcome": "denied"}) == 2
            assert metrics.get_sample_value("auction_bot_command_errors_total", {"outcome": "error"}) == 2
        finally:
            await client.stop()
            await bot.services.runtime.close()

    asyncio.run(scenario())


def test_failed_check_waits_for_sibling_and_records_partial_cycle():
    async def scenario():
        held, release, completed = asyncio.Event(), asyncio.Event(), []

        async def check(provider, item):
            if item["id"] == 1:
                raise RuntimeError("provider unavailable")
            if item["id"] == 2:
                held.set()
                await release.wait()
            completed.append(item["id"])

        runtime = build_runtime(check, [alert(1), alert(2), alert(3)])
        cycle = asyncio.create_task(runtime.poll_cycle())
        await asyncio.wait_for(held.wait(), 1)
        await asyncio.sleep(0)
        assert not cycle.done()
        assert runtime.health.last_poll is None
        release.set()
        await asyncio.wait_for(cycle, 1)
        assert sorted(completed) == [2, 3]
        assert value(runtime, "polls_total", {"outcome": "partial"}) == 1
        assert value(runtime, "last_poll_completed_timestamp_seconds") > 0
        assert value(runtime, "last_poll_success_timestamp_seconds") == 0
        assert value(runtime, "active_checks") == 0

    asyncio.run(scenario())


def test_the_status_page_gets_each_searchs_last_check_from_memory():
    async def scenario():
        async def check(provider, item):
            if item["id"] == 1:
                raise RuntimeError("https://example.com/search?q=secret answered 500")

        runtime = build_runtime(check, [alert(1), alert(2)])
        await runtime.poll_cycle()
        status = runtime.status()
        failed, passed = status["checks"][1][0], status["checks"][2][0]
        # Only the error's type: its message can hold a marketplace URL.
        assert (failed["outcome"], failed["error"]) == ("error", "RuntimeError")
        assert (passed["outcome"], passed["error"]) == ("success", None)
        assert status["last_poll_at"] is not None and status["last_success_at"] is None
        # Results of a search that was unregistered go with it on the next cycle.
        runtime.repository.alerts = [alert(2)]
        await runtime.poll_cycle()
        assert set(runtime.status()["checks"]) == {2}
        assert runtime.status()["last_success_at"] is not None

    asyncio.run(scenario())


def test_worker_pool_is_bounded_and_never_skips_a_query():
    async def scenario():
        active, peak, seen, tasks = 0, 0, [], set()

        async def check(provider, item):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            tasks.add(asyncio.current_task())
            await asyncio.sleep(0)
            seen.append(item["id"])
            active -= 1

        settings = replace(Settings(), concurrency=3, monitoring_enabled=False, dashboard_enabled=False)
        rows = [alert(index, "BABYMETAL BEGINS" if index == 0 else "query") for index in range(1000)]
        runtime = build_runtime(check, rows, settings)
        await runtime.poll_cycle()
        assert sorted(seen) == list(range(1000))
        assert peak == 3
        assert len(tasks) == 3
        assert value(runtime, "checks_total", {"source": "yahooauction", "outcome": "success"}) == 1000
        assert value(runtime, "source_last_success_timestamp_seconds", {"source": "yahooauction"}) > 0

    asyncio.run(scenario())


def test_cycle_cancellation_settles_checks_and_releases_gauge():
    async def scenario():
        running, cleaned = asyncio.Event(), []

        async def check(provider, item):
            running.set()
            try:
                await asyncio.Future()
            finally:
                cleaned.append(item["id"])

        runtime = build_runtime(check, [alert(1), alert(2)])
        cycle = asyncio.create_task(runtime.poll_cycle())
        await asyncio.wait_for(running.wait(), 1)
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
        assert sorted(cleaned) == [1, 2]
        assert value(runtime, "active_checks") == 0
        assert runtime.health.last_poll is None
        assert not any(task.get_name().startswith("auction-bot:check-worker:")
                       for task in asyncio.all_tasks() if task is not asyncio.current_task())

    asyncio.run(scenario())


def test_timeout_preserves_last_success_and_advances_completed_timestamp():
    async def scenario():
        fail = False

        async def check(provider, item):
            if fail:
                await asyncio.Future()

        runtime = build_runtime(check, [alert(1)], replace(Settings(), check_timeout=.01, monitoring_enabled=False, dashboard_enabled=False))
        await runtime.poll_cycle()
        previous_success = value(runtime, "last_poll_success_timestamp_seconds")
        previous_source_success = value(runtime, "source_last_success_timestamp_seconds", {"source": "yahooauction"})
        fail = True
        await runtime.poll_cycle()
        assert value(runtime, "last_poll_success_timestamp_seconds") == previous_success
        assert value(runtime, "source_last_success_timestamp_seconds", {"source": "yahooauction"}) == previous_source_success
        assert value(runtime, "last_poll_completed_timestamp_seconds") > previous_success
        assert value(runtime, "checks_total", {"source": "yahooauction", "outcome": "timeout"}) == 1
        assert value(runtime, "alert_checks_total", {
            "alert_id": "1", "source": "yahooauction", "outcome": "timeout"}) == 1
        assert value(runtime, "alert_info", {
            "alert_id": "1", "search_query": "query", "channel_id": "10"}) == 1

    asyncio.run(scenario())


def test_recoverable_database_cycle_error_is_retried():
    async def scenario():
        checked = asyncio.Event()

        async def check(provider, item):
            checked.set()

        runtime = build_runtime(check, [alert(1)], replace(Settings(), interval=.001, monitoring_enabled=False, dashboard_enabled=False))
        original = runtime.repository.list_alerts
        reads = 0

        async def sometimes_fails():
            nonlocal reads
            reads += 1
            if reads == 1:
                raise OSError("database temporarily busy")
            return await original()

        runtime.repository.list_alerts = sometimes_fails
        task = asyncio.create_task(runtime.poll_forever())
        try:
            await asyncio.wait_for(checked.wait(), 1)
            await asyncio.sleep(0)
            assert reads >= 2
            assert value(runtime, "polls_total", {"outcome": "error"}) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_prepare_does_not_poll_before_started_and_start_is_idempotent():
    async def scenario():
        checked = asyncio.Event()

        async def check(provider, item):
            checked.set()

        runtime = build_runtime(check, [alert(1)])
        await runtime.prepare()
        assert runtime.repository.started and runtime.http.started
        assert not runtime.tasks and not checked.is_set()
        runtime.set_connected(0)
        await runtime.start()
        tasks = dict(runtime.tasks)
        await runtime.start()
        assert tasks == runtime.tasks
        await asyncio.wait_for(checked.wait(), 1)
        await asyncio.sleep(0)
        assert runtime.health.status()[0]
        await runtime.close()
        assert all(task.done() for task in tasks.values())
        assert runtime.repository.closed and runtime.http.closed
        assert not runtime.health.status()[0]

    asyncio.run(scenario())


def test_critical_worker_death_marks_unready_and_shuts_down():
    async def scenario():
        class FailedDelivery:
            async def run(self):
                raise RuntimeError("worker failed")

        async def check(provider, item):
            pass

        runtime = build_runtime(check, delivery=FailedDelivery())
        runtime.set_connected(0)
        await runtime.start()
        await asyncio.wait_for(runtime.bot.closed.wait(), 1)
        assert isinstance(runtime.failure, RuntimeError)
        assert runtime.health.failed_worker == "delivery"
        assert not runtime.health.status()[0]
        assert all(task.done() for task in runtime.tasks.values())
        assert runtime.repository.closed and runtime.http.closed

    asyncio.run(scenario())


def test_readiness_requires_every_local_gateway_shard_and_database():
    async def scenario():
        async def check(provider, item):
            pass

        runtime = build_runtime(check)
        runtime.set_expected_shards([0, 1])
        runtime.set_connected(0)
        await runtime.start()
        await asyncio.sleep(0)
        assert not runtime.health.status()[0]
        runtime.set_connected(1)
        assert runtime.health.status()[0]
        runtime.set_disconnected(0)
        assert not runtime.health.status()[0]
        runtime.set_connected(0)
        runtime.health.repository_available = False
        assert not runtime.health.status()[0]
        await runtime.close()

    asyncio.run(scenario())
