"""Application lifecycle and supervised, bounded marketplace polling.

Providers, persistence and Discord delivery are injected into this layer. The
poller owns orchestration only; it never posts messages or handles ORM objects.
"""
import asyncio
from collections import defaultdict
import logging
import time
from uuid import uuid4

from observability import Health, MonitoringServer, log_context, watch_loop


logger = logging.getLogger(__name__)


class Runtime:
    def __init__(self, bot, settings, repository, http, ingestion, delivery, providers, metrics,
                 dashboard_server=None):
        self.bot, self.settings = bot, settings
        self.repository, self.http = repository, http
        self.ingestion, self.delivery = ingestion, delivery
        # Adapters are shared across alerts/cycles, retaining connection pools
        # and bounded provider caches for the lifetime of the application.
        self.providers, self.metrics = providers, metrics
        self.health = Health(settings.health_max_poll_age,
                             max_stats_age=max(30, 3 * settings.metrics_stats_interval))
        self.monitoring = MonitoringServer(settings, metrics, self.health)
        self.dashboard = dashboard_server
        # The newest finished check of each alert and source, for the dashboard's status page.
        # Kept in memory only: after a restart a search has no result until it is checked again.
        self.check_results = {}
        # Source to the wall-clock time of its last cycle without failed checks.
        self.source_success = {}
        # Sources the bot searches that no search checks. They export no success time, so they never
        # look stale; when a search checks one again its staleness counts from then, as after a start.
        self.idle_sources = set()
        self._history_pruned_at = None
        self._history_prune_backlog = False
        self.tasks = self.health.tasks
        self.failure = None
        self._connected_shards = set()
        self._expected_shards = set()
        self._prepared = False
        self._started = False
        self._closed = False
        self._failure_task = None
        self.metrics.poll_interval.set(settings.interval)
        self.metrics.max_poll_age.set(settings.health_max_poll_age)
        self.metrics.stats_interval.set(settings.metrics_stats_interval)
        self.metrics.ready.set_function(lambda: int(self.health.status()[0]))
        for source in self.providers:
            self.metrics.source_last_success.labels(source).set(0)
            for outcome in ("success", "error", "timeout", "cancelled"):
                self.metrics.checks.labels(source, outcome)

    async def prepare(self):
        """Open owned resources before the gateway is ready; do not poll yet."""
        if self._prepared:
            return
        if self._closed:
            raise RuntimeError("A closed runtime cannot be restarted")
        try:
            await self.repository.start()
            await self.http.start()
            await self.monitoring.start()
            if self.dashboard is not None:
                await self.dashboard.start()
        except Exception:
            await self.close()
            raise
        self._prepared = True
        logger.info("runtime_prepared", extra={"fields": {"sources": list(self.providers)}})

    def set_expected_shards(self, shard_ids):
        self._expected_shards = set(shard_ids)
        self._update_gateway()

    def set_connected(self, shard_id):
        self._connected_shards.add(shard_id)
        self._update_gateway()

    def set_disconnected(self, shard_id):
        self._connected_shards.discard(shard_id)
        self._update_gateway()

    def _update_gateway(self):
        self.health.connected = bool(self._connected_shards) and (
            not self._expected_shards or self._expected_shards <= self._connected_shards
        )
        self.metrics.gateway.set(int(self.health.connected))

    async def start(self):
        """Start workers once, after Hikari's StartedEvent."""
        if self._started:
            return
        await self.prepare()
        self.health.started = time.monotonic()
        self.metrics.started.set(time.time())
        self._started = True
        self._spawn("poller", self.poll_forever())
        self._spawn("delivery", self.delivery.run())
        self._spawn("event_loop", watch_loop(self.metrics))
        self._spawn("database_stats", self.watch_stats())
        logger.info("runtime_started")

    def _spawn(self, name, coroutine):
        task = asyncio.create_task(coroutine, name=f"auction-bot:{name}")
        self.tasks[name] = task
        self.metrics.worker_alive.labels(name).set(1)
        task.add_done_callback(lambda finished: self._worker_done(name, finished))

    def _worker_done(self, name, task):
        self.metrics.worker_alive.labels(name).set(0)
        if self.health.stopping:
            return
        error = None if task.cancelled() else task.exception()
        self.failure = error or RuntimeError(f"Worker {name} unexpectedly stopped")
        self.health.failed_worker = name
        logger.critical("worker_stopped", extra={"fields": {"worker": name}},
                        exc_info=(type(error), error, error.__traceback__) if error else None)
        # Retain the shutdown task. StoppingEvent calls close(), so close must
        # not await this task and introduce a shutdown dependency cycle.
        if self._failure_task is None:
            self._failure_task = asyncio.create_task(self._shutdown_bot(), name="auction-bot:fatal-shutdown")

    async def _shutdown_bot(self):
        try:
            await self.bot.close()
        except Exception:
            logger.exception("gateway_shutdown_failed")
            await self.close()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self.health.stopping = True
        self.health.connected = False
        self.metrics.gateway.set(0)
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        # Close each resource even if another resource reports an error.
        for name, resource in (("dashboard", self.dashboard), ("monitoring", self.monitoring), ("http", self.http),
                               ("repository", self.repository)):
            if resource is None:
                continue
            try:
                await resource.close()
            except Exception:
                logger.exception("resource_close_failed", extra={"fields": {"resource": name}})
        logger.info("runtime_stopped")

    async def poll_forever(self):
        while True:
            try:
                await self.poll_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Failed reads and other recoverable cycle errors must not
                # permanently stop the scheduler. Children have already settled.
                logger.exception("poll_cycle_failed")
            await asyncio.sleep(self.settings.interval)

    async def poll_cycle(self):
        """Settle every check before sleeping, with only N worker tasks."""
        cycle_id = uuid4().hex
        context = log_context.set({"cycle_id": cycle_id})
        started, started_at = time.monotonic(), time.time()
        outcome = "error"
        settled = False
        workers = []
        results = defaultdict(lambda: [0, 0])
        try:
            alerts = await self.repository.list_alerts()
            states = await self.repository.source_states()
            self.metrics.alerts.set(len(alerts))
            self.metrics.update_alert_metadata(alerts)
            # Each search checks the marketplaces the bot searches that it has not turned off. One it
            # has not seeded yet saves what it finds without posting (see Ingestion.check).
            jobs = []
            for alert in alerts:
                for source, provider in self.providers.items():
                    enabled, seeded = states.get(alert["id"], {}).get(source, (True, False))
                    if enabled:
                        jobs.append((source, provider, alert, not seeded))
            pairs = {(alert["id"], source) for source, _, alert, _ in jobs}
            self.check_results = {key: value for key, value in self.check_results.items() if key in pairs}
            queue = iter(jobs)

            async def worker():
                for source, provider, alert, seeding in queue:
                    result = await self._run_check(source, provider, alert, seeding)
                    results[source][0] += 1
                    results[source][1] += result != "success"

            count = min(self.settings.concurrency, len(jobs))
            workers = [asyncio.create_task(worker(), name=f"auction-bot:check-worker:{index}")
                       for index in range(count)]
            if workers:
                # Never return on the first failure while sibling checks remain
                # running. Expected per-check failures are contained below.
                for result in await asyncio.gather(*workers, return_exceptions=True):
                    if isinstance(result, BaseException):
                        raise result
            failures = sum(failed for _, failed in results.values())
            outcome = "partial" if failures else "success"
            now = time.time()
            used = {source for source, *_ in jobs}
            for source in self.providers:
                if source not in used and source not in self.idle_sources:
                    self.metrics.source_last_success.remove(source)
                    self.idle_sources.add(source)
                elif source in used and source in self.idle_sources:
                    self.metrics.source_last_success.labels(source).set(started_at)
                    self.idle_sources.discard(source)
            for source, (checked, failed) in results.items():
                if checked and not failed:
                    self.metrics.source_last_success.labels(source).set(now)
                    self.source_success[source] = now
            if outcome == "success":
                self.metrics.last_success.set(now)
                self.health.last_success = time.monotonic()
            logger.info("poll_completed", extra={"fields": {
                "outcome": outcome, "alerts": len(alerts),
                "checks": sum(checked for checked, _ in results.values()), "failed_checks": failures,
                "duration_seconds": round(time.monotonic() - started, 3),
            }})
            settled = True
        except asyncio.CancelledError:
            raise
        except Exception:
            settled = True
            raise
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            if settled:
                self.metrics.polls.labels(outcome).inc()
                self.metrics.poll_duration.observe(time.monotonic() - started)
                self.metrics.last_poll.set(time.time())
                self.health.last_poll = time.monotonic()
            log_context.reset(context)

    async def _run_check(self, source, provider, alert, seeding=False):
        context = log_context.set({**log_context.get(), "source": source, "alert_id": alert["id"]})
        started = time.monotonic()
        outcome = "cancelled"
        error_name = None
        identity = (alert["search_query"], str(alert["channel_id"]))
        self.metrics.begin_check(alert["id"], source, identity)
        self.metrics.active_checks.inc()
        try:
            async with asyncio.timeout(self.settings.check_timeout):
                await self.ingestion.check(provider, alert, seeding=seeding)
            outcome = "success"
        except TimeoutError:
            outcome = "timeout"
            logger.warning("check_timed_out", extra={"fields": {"timeout_seconds": self.settings.check_timeout}})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            outcome, error_name = "error", type(error).__name__
            logger.exception("check_failed")
        finally:
            duration = time.monotonic() - started
            self.metrics.active_checks.dec()
            self.metrics.observe_check(alert["id"], source, outcome, duration, identity)
            if outcome != "cancelled":
                # Only the error's type: its message can hold a marketplace URL or response text.
                self.check_results[(alert["id"], source)] = {
                    "source": source, "outcome": outcome, "finished_at": time.time(),
                    "duration_seconds": round(duration, 3), "error": error_name}
            log_context.reset(context)
        return outcome

    async def watch_stats(self):
        while True:
            try:
                now = time.monotonic()
                if hasattr(self.repository, "prune_candidates") and (
                        self._history_prune_backlog or self._history_pruned_at is None
                        or now - self._history_pruned_at >= 60):
                    result = await self.repository.prune_candidates(
                        self.settings.history_retention_days, self.settings.history_max_rows)
                    self._history_prune_backlog = result["has_more"]
                    self._history_pruned_at = now
                stats = await self.repository.stats()
                self.metrics.alerts.set(stats["alerts"])
                self.metrics.update_alert_metadata(stats["alert_metadata"])
                self.metrics.pending.set(stats["pending"])
                self.metrics.failed.set(stats["failed"])
                self.metrics.oldest_pending.set(stats["oldest_pending_age"])
                self.metrics.filters_disabled.set(stats["disabled_legacy_filters"])
                self.metrics.stats_refreshed.set(time.time())
                self.health.last_stats = time.monotonic()
                self.health.repository_available = True
            except asyncio.CancelledError:
                raise
            except Exception:
                self.health.repository_available = False
                logger.exception("database_stats_failed")
            await asyncio.sleep(self.settings.metrics_stats_interval)

    def status(self):
        """What the dashboard's status page shows about the running bot, from memory only."""
        ready, health = self.health.status()

        def wall(moment):
            # Health keeps monotonic times; the page wants clock times.
            return None if moment is None else time.time() - (time.monotonic() - moment)
        checks = {}
        for (alert_id, _), result in sorted(self.check_results.items()):
            checks.setdefault(alert_id, []).append(dict(result))
        return {"ready": ready, "discord_connected": health["discord_connected"],
                "database_available": health["database_available"], "failed_worker": health["failed_worker"],
                "last_poll_at": wall(self.health.last_poll), "last_success_at": wall(self.health.last_success),
                "started_at": wall(self.health.started), "interval_seconds": self.settings.interval,
                "sources": {source: self.source_success.get(source) for source in self.providers},
                "checks": checks}
