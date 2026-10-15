"""Bounded-label metrics, structured logging and operational health endpoints."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import time

from aiohttp import web
from prometheus_client import (CollectorRegistry, Counter, Gauge, Histogram, generate_latest,
                               GCCollector, PlatformCollector, ProcessCollector)
from prometheus_client import CONTENT_TYPE_LATEST

log_context = ContextVar("log_context", default={})


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets=()):
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def _redact(self, value):
        if isinstance(value, dict):
            return {key: "[redacted]" if str(key).lower() in {
                "token", "bot_token", "authorization", "password", "secret",
                "review_token", "access_key", "cookie"
            } else self._redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(item) for item in value]
        if not isinstance(value, (str, int, float, bool, type(None))):
            value = str(value)
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[redacted]")
        return value

    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name,
            "event": record.getMessage(), **log_context.get(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(self._redact(payload), ensure_ascii=False, default=str)


def configure_logging(level, secrets=()):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(secrets))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # Request URLs can contain search queries; do not emit access logs.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        GCCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        ProcessCollector(registry=self.registry)
        def counter(name, help, labels=()):
            return Counter("auction_bot_" + name, help, labels, registry=self.registry)
        def gauge(name, help, labels=()):
            return Gauge("auction_bot_" + name, help, labels, registry=self.registry)
        def histogram(name, help, labels=(), buckets=(.01, .05, .1, .5, 1, 5, 15, 30, 60, 300, 600)):
            return Histogram("auction_bot_" + name, help, labels, buckets=buckets, registry=self.registry)
        self.polls = counter("polls_total", "Completed poll cycles", ("outcome",))
        self.poll_duration = histogram("poll_duration_seconds", "Poll cycle duration")
        self.last_poll = gauge("last_poll_completed_timestamp_seconds", "Last completed poll, including partial failures")
        self.last_success = gauge("last_poll_success_timestamp_seconds", "Last fully successful poll")
        self.source_last_success = gauge("source_last_success_timestamp_seconds", "Last cycle with successful checks for a source", ("source",))
        self.started = gauge("started_timestamp_seconds", "Worker startup timestamp")
        self.poll_interval = gauge("configured_poll_interval_seconds", "Configured delay between settled poll cycles")
        self.max_poll_age = gauge("health_max_poll_age_seconds", "Configured maximum time since completed poll")
        self.stats_interval = gauge("configured_stats_interval_seconds", "Configured database statistics refresh interval")
        self.ready = gauge("ready", "Readiness including gateway, workers, database and scheduler")
        self.checks = counter("checks_total", "Completed alert/source checks", ("source", "outcome"))
        self.check_duration = histogram("check_duration_seconds", "Alert/source check duration", ("source",))
        self.alert_checks = counter("alert_checks_total", "Checks for a configured alert", ("alert_id", "source", "outcome"))
        self.alert_check_duration = histogram("alert_check_duration_seconds", "Check duration for a configured alert", ("alert_id", "source"))
        self.alert_info = gauge("alert_info", "Configured alert metadata; value is always 1", ("alert_id", "search_query", "channel_id"))
        self._alert_labels = {}
        self._alert_check_labels = {}
        self._alert_duration_labels = {}
        self.active_checks = gauge("active_checks", "Active marketplace checks")
        self.requests = counter("provider_requests_total", "Provider request attempts", ("source", "operation", "outcome"))
        self.request_duration = histogram("provider_request_duration_seconds", "Provider attempt latency", ("source", "operation"))
        self.items = counter("items_total", "Observed listing decisions", ("source", "outcome"))
        self.db_duration = histogram("database_operation_duration_seconds", "Repository operation duration including queue wait", ("operation",))
        self.db_errors = counter("database_errors_total", "Failed repository operations", ("operation",))
        self.deliveries = counter("delivery_attempts_total", "Delivery attempts", ("kind", "outcome"))
        self.delivery_duration = histogram("delivery_duration_seconds", "Discord delivery attempt duration", ("kind",))
        self.pending = gauge("outbox_pending", "Pending delivery jobs")
        self.failed = gauge("outbox_failed", "Delivery jobs requiring operator intervention")
        self.oldest_pending = gauge("outbox_oldest_pending_age_seconds", "Age of oldest pending job")
        self.alerts = gauge("configured_alerts", "Registered search alerts")
        self.filters_disabled = gauge("disabled_legacy_filters", "Legacy filters requiring matcher selection")
        self.stats_refreshed = gauge("database_stats_refreshed_timestamp_seconds", "Last successful outbox and alert statistics refresh")
        self.worker_alive = gauge("worker_alive", "Worker task running", ("worker",))
        self.loop_lag = histogram("event_loop_lag_seconds", "Event loop scheduling delay", buckets=(.001, .005, .01, .05, .1, .5, 1, 5))
        self.gateway = gauge("discord_connected", "Discord gateway connection state")
        self.reaction_errors = counter("reaction_errors_total", "Reaction handler failures")
        self.command_errors = counter("command_errors_total", "Slash command failures", ("outcome",))
        self.review_requests = counter("review_requests_total", "Filter Lab HTTP requests",
                                       ("operation", "outcome"))
        self.review_duration = histogram("review_request_duration_seconds", "Filter Lab request duration",
                                         ("operation",))
        for outcome in ("success", "partial", "error"):
            self.polls.labels(outcome)
        for outcome in ("denied", "error"):
            self.command_errors.labels(outcome)
        for kind in ("channel", "dm"):
            for outcome in ("sent", "retry", "failed", "cancelled"):
                self.deliveries.labels(kind, outcome)
        for worker in ("poller", "delivery", "event_loop", "database_stats"):
            self.worker_alive.labels(worker).set(0)

    def update_alert_metadata(self, alerts):
        """Publish one lookup series per alert and retire removed/replaced identities."""
        current = {str(alert["id"]): (alert["search_query"], str(alert["channel_id"]))
                   for alert in alerts}
        for identifier, labels in self._alert_labels.items():
            if current.get(identifier) != labels:
                self.alert_info.remove(identifier, *labels)
                for source, outcome in self._alert_check_labels.pop(identifier, set()):
                    self.alert_checks.remove(identifier, source, outcome)
                for source in self._alert_duration_labels.pop(identifier, set()):
                    self.alert_check_duration.remove(identifier, source)
        for identifier, labels in current.items():
            if self._alert_labels.get(identifier) != labels:
                self.alert_info.labels(identifier, *labels).set(1)
        self._alert_labels = current

    def observe_check(self, alert_id, source, outcome, duration, identity=None):
        self.checks.labels(source, outcome).inc()
        self.check_duration.labels(source).observe(duration)
        identifier = str(alert_id)
        # A check can finish after its alert was unregistered; do not recreate retired series.
        if identifier not in self._alert_labels or (
                identity is not None and self._alert_labels[identifier] != identity):
            return
        self.alert_checks.labels(identifier, source, outcome).inc()
        self.alert_check_duration.labels(identifier, source).observe(duration)
        self._alert_check_labels.setdefault(identifier, set()).add((source, outcome))
        self._alert_duration_labels.setdefault(identifier, set()).add(source)

    def begin_check(self, alert_id, source, identity=None):
        identifier = str(alert_id)
        if identifier not in self._alert_labels or (
                identity is not None and self._alert_labels[identifier] != identity):
            return
        for outcome in ("success", "error", "timeout", "cancelled"):
            self.alert_checks.labels(identifier, source, outcome)
            self._alert_check_labels.setdefault(identifier, set()).add((source, outcome))
        self.alert_check_duration.labels(identifier, source)
        self._alert_duration_labels.setdefault(identifier, set()).add(source)


@dataclass
class Health:
    max_poll_age: int
    max_stats_age: int = 30
    started: float = field(default_factory=time.monotonic)
    last_poll: float | None = None
    last_success: float | None = None
    last_stats: float | None = None
    connected: bool = False
    repository_available: bool = False
    failed_worker: str | None = None
    stopping: bool = False
    tasks: dict = field(default_factory=dict)

    def status(self):
        workers = {name: not task.done() for name, task in self.tasks.items()}
        age = time.monotonic() - (self.last_poll if self.last_poll is not None else self.started)
        database_available = self.repository_available and (
            self.last_stats is None or time.monotonic() - self.last_stats <= self.max_stats_age
        )
        ready = (self.connected and database_available and not self.stopping
                 and not self.failed_worker and bool(workers)
                 and all(workers.values()) and age <= self.max_poll_age)
        return ready, {"ready": ready, "discord_connected": self.connected,
                       "database_available": database_available,
                       "failed_worker": self.failed_worker,
                       "workers": workers, "poll_age_seconds": round(age, 3),
                       "last_success_age_seconds": (None if self.last_success is None else
                                                     round(time.monotonic() - self.last_success, 3))}


class MonitoringServer:
    def __init__(self, settings, metrics, health):
        self.settings, self.metrics, self.health = settings, metrics, health
        self.runner = None

    async def start(self):
        if not self.settings.monitoring_enabled:
            return
        app = web.Application()
        app.router.add_get("/metrics", self.scrape)
        app.router.add_get("/health/live", self.live)
        app.router.add_get("/health/ready", self.ready)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, self.settings.monitoring_host, self.settings.monitoring_port).start()

    async def scrape(self, request):
        return web.Response(body=generate_latest(self.metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    async def live(self, request):
        return web.json_response({"live": not self.health.stopping}, status=503 if self.health.stopping else 200)

    async def ready(self, request):
        ready, payload = self.health.status()
        return web.json_response(payload, status=200 if ready else 503)

    async def close(self):
        if self.runner:
            await self.runner.cleanup()


async def watch_loop(metrics):
    while True:
        expected = time.monotonic() + 1
        await asyncio.sleep(1)
        metrics.loop_lag.observe(max(0, time.monotonic() - expected))
