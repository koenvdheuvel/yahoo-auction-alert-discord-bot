"""The Status page's graphs: panels of the Grafana dashboard, drawn from the same Prometheus.

monitoring/grafana-dashboard.json defines every graph once: its title, its explanation (the
panel description), its unit, how it is drawn and its PromQL. Grafana draws the panels from that
file. The dashboard reads the panels listed in PANELS from the same file, runs their PromQL
against PROMETHEUS_URL with Grafana's variables filled in, and the Status page draws the results.
Change a panel in Grafana, export the dashboard to that file, and the Status page follows.

A server only sees its own searches. A series that names a search carries its alert_id and is
kept only when that alert is one of the server's searches, under the same name and channel. The
other series count the whole bot. The browser picks one of RANGES; it never sends PromQL.
"""
import asyncio
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path
import re
import time

import aiohttp


logger = logging.getLogger(__name__)

DASHBOARD = Path(__file__).resolve().parent / "monitoring" / "grafana-dashboard.json"
# Grafana panel IDs, in the order the Status page shows them, each under its Grafana row's title.
PANELS = (14, 15, 16, 19, 20, 21, 23, 24, 26, 27)
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
DEFAULT_RANGE = "24h"
# Points per graph. Grafana takes about one per pixel; a card on the Status page needs fewer.
POINTS = 120
# monitoring/prometheus.yml scrapes the bot every 15 seconds, which $__rate_interval builds on.
SCRAPE_SECONDS = 15
# Answers are shared by every server and browser tab for this long, so open Status pages do
# not add up to more Prometheus queries.
CACHE_SECONDS = 30
TIMEOUT_SECONDS = 10
# The same for every series of one bot, or of no use on the Status page.
HIDDEN_LABELS = frozenset({"__name__", "job", "instance"})
# Labels that name one search. Grafana's alert_info lookup carries the last two.
SEARCH_LABELS = ("alert_id", "search_query", "channel_id")
VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
VARIABLES = frozenset({"instance", "__interval", "__rate_interval", "__range"})
SEVERAL_BOTS = ("Prometheus has more than one bot under the job auction-bot, so these graphs add them "
                "together and the graphs about single searches are left out. The bot's operator can set "
                "PROMETHEUS_INSTANCE to this bot's instance.")


class GraphError(Exception):
    """Prometheus could not answer one panel's query. The message is shown on the panel."""


@dataclass(frozen=True)
class Target:
    expr: str
    legend: str
    instant: bool


@dataclass(frozen=True)
class Panel:
    id: int
    section: str
    title: str
    description: str
    kind: str
    unit: str
    decimals: int | None
    style: str
    stacked: bool
    # Tables only, from Grafana's organize transformation: (label, title) per column before the
    # number, the number's title, and the labels Grafana leaves out.
    columns: tuple
    value_title: str
    hidden_columns: frozenset
    targets: tuple
    # "server" when its series are about single searches, which each server only sees its own of.
    scope: str


def load_panels(path=DASHBOARD, ids=PANELS):
    """The panels with these IDs from a Grafana dashboard export, in this order.

    Raises ValueError for a panel the Status page cannot draw, so a dashboard change that breaks
    the Status page stops startup instead of showing broken graphs.
    """
    found, section = {}, ""
    for raw in json.loads(Path(path).read_text(encoding="utf-8")).get("panels", []):
        if raw.get("type") == "row":
            section = raw.get("title", "")
            # A collapsed row keeps its panels inside it.
            for child in raw.get("panels", []):
                found[child.get("id")] = (section, child)
        else:
            found[raw.get("id")] = (section, raw)
    panels = []
    for panel_id in ids:
        if panel_id not in found:
            raise ValueError(f"The Grafana dashboard has no panel {panel_id}")
        panels.append(_panel(*found[panel_id]))
    return tuple(panels)


def _panel(section, raw):
    name = f"Grafana panel {raw.get('id')} ({raw.get('title', '')})"
    kind = raw.get("type")
    if kind not in {"timeseries", "table"}:
        raise ValueError(f"{name} is a {kind} panel; the Status page draws time series and tables")
    if (raw.get("datasource") or {}).get("type") != "prometheus":
        raise ValueError(f"{name} does not query Prometheus")
    targets = []
    for target in raw.get("targets") or []:
        if target.get("hide"):
            continue
        expr = target.get("expr", "")
        for match in VARIABLE.finditer(expr):
            if (match.group(1) or match.group(2)) not in VARIABLES:
                raise ValueError(f"{name} uses {match.group()}, which the Status page cannot fill in")
        instant = bool(target.get("instant")) and not target.get("range")
        if instant != (kind == "table"):
            raise ValueError(f"{name} needs {'instant' if kind == 'table' else 'range'} queries")
        # The Status page shows one bot, so the instance would only repeat on every series.
        legend = " ".join(re.sub(r"\{\{\s*instance\s*\}\}", "", target.get("legendFormat", "")).split())
        targets.append(Target(expr, legend, instant))
    if not targets:
        raise ValueError(f"{name} has no query")
    defaults = (raw.get("fieldConfig") or {}).get("defaults") or {}
    custom = defaults.get("custom") or {}
    columns, value_title, hidden = _columns(raw) if kind == "table" else ((), "", frozenset())
    return Panel(
        id=raw["id"], section=section, title=raw.get("title", ""),
        description=" ".join(raw.get("description", "").split()), kind=kind,
        unit=defaults.get("unit") or "none", decimals=defaults.get("decimals"),
        style="bars" if custom.get("drawStyle") == "bars" else "line",
        stacked=(custom.get("stacking") or {}).get("mode", "none") != "none",
        columns=columns, value_title=value_title, hidden_columns=hidden, targets=tuple(targets),
        # Its own series carry alert_id only when the query keeps it.
        scope="server" if any("alert_id" in target.expr for target in targets) else "bot")


def _columns(raw):
    organize = next((transformation.get("options") or {} for transformation in raw.get("transformations") or []
                     if transformation.get("id") == "organize"), {})
    renamed = organize.get("renameByName") or {}
    # alert_id links a row to its search instead of being shown.
    hidden = frozenset({name for name, excluded in (organize.get("excludeByName") or {}).items() if excluded}
                       | HIDDEN_LABELS | {"Time", "alert_id"})
    columns = tuple((name, title) for name, title in renamed.items() if name not in hidden | {"Value"})
    return columns, renamed.get("Value", "Value"), hidden


def instance_pattern(instance):
    """What fills in instance=~"$instance": exactly this instance, or every one when it is empty."""
    if not instance:
        return ".+"
    pattern = re.sub(r"[\\.+*?()|\[\]{}^$]", lambda match: "\\" + match.group(), instance)
    # Then written inside a PromQL string, where a backslash is escaped too.
    return pattern.replace("\\", "\\\\").replace('"', '\\"')


def render(expr, instance, step, seconds):
    """expr with Grafana's variables filled in as Grafana does for a graph with this step."""
    values = {
        "instance": instance,
        "__interval": f"{step}s",
        "__rate_interval": f"{max(step + SCRAPE_SECONDS, 4 * SCRAPE_SECONDS)}s",
        "__range": f"{seconds}s",
    }
    return VARIABLE.sub(lambda match: values[match.group(1) or match.group(2)], expr)


def number(text):
    """A sample value; Prometheus writes NaN and infinities as strings, and JSON cannot carry them."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def visible(labels, scope, searches):
    """Whether one server may see a series. searches maps the server's alert IDs to their search."""
    alert_id = labels.get("alert_id")
    if alert_id is None:
        # About no single search: the whole bot. A panel about searches only shows its searches.
        return scope == "bot" and not any(name in labels for name in SEARCH_LABELS)
    search = searches.get(alert_id)
    # Alert IDs are reused after a search is deleted, so the old search must not show as this one.
    return search is not None and all(labels[name] == search[name] for name in SEARCH_LABELS[1:] if name in labels)


class Prometheus:
    """The few calls of Prometheus' HTTP API that the graphs need."""

    def __init__(self, url, timeout=TIMEOUT_SECONDS):
        self.url = url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None

    async def query(self, expr, **params):
        """The result list of a query: a range query with start, end and step, else an instant one."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        path = "query_range" if "step" in params else "query"
        form = {"query": expr, **{name: str(value) for name, value in params.items()}}
        try:
            async with self.session.post(f"{self.url}/api/v1/{path}", data=form) as response:
                status = response.status
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise GraphError("Prometheus did not answer.") from None
        if not isinstance(body, dict):
            raise GraphError(f"Prometheus answered HTTP {status} without a result.")
        if body.get("status") != "success":
            reason = " ".join(str(body.get("error") or "no reason given").split())[:300]
            raise GraphError(f"Prometheus could not run this graph's query: {reason}")
        data = body.get("data") or {}
        expected = "matrix" if path == "query_range" else "vector"
        if data.get("resultType") != expected or not isinstance(data.get("result"), list):
            raise GraphError(f"Prometheus answered with a {data.get('resultType')} instead of a {expected}.")
        return data["result"]

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None


def disabled(span):
    """The answer without Prometheus: nothing to draw."""
    return {"enabled": False, "range": span, "ranges": list(RANGES), "start": None, "end": None, "step": None,
            "times": [], "warning": None, "sections": []}


class Graphs:
    """The Status page's graphs. DashboardServer has one when PROMETHEUS_URL is set."""

    def __init__(self, url, instance="", panels=None):
        self.panels = load_panels() if panels is None else tuple(panels)
        self.prometheus = Prometheus(url)
        self.instance, self.scoped = instance_pattern(instance), bool(instance)
        # Range to (expiry, task). One round of queries per range at a time, shared by everyone.
        self.cache = {}

    @classmethod
    def from_settings(cls, settings):
        return cls(settings.prometheus_url, settings.prometheus_instance) if settings.prometheus_url else None

    async def close(self):
        tasks = [task for _, task in self.cache.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.cache.clear()
        await self.prometheus.close()

    async def for_server(self, span, searches):
        """The graphs one server sees. searches maps its alert IDs, as strings, to a dict with the
        search_query and channel_id (a string) of each."""
        collected = await self.collect(span)
        several = len(collected["instances"]) > 1
        sections = []
        for panel, error, series in collected["panels"]:
            if several and panel.scope == "server":
                error, series = SEVERAL_BOTS, []
            shown = [entry for entry in series if visible(entry[1], panel.scope, searches)]
            body = {"id": panel.id, "title": panel.title, "description": panel.description, "kind": panel.kind,
                    "unit": panel.unit, "decimals": panel.decimals, "scope": panel.scope, "error": error}
            if panel.kind == "table":
                columns = list(panel.columns)
                # Labels Grafana would show too, under their own names.
                columns += [(name, name) for name in sorted(
                    {name for _, labels, _ in shown for name in labels}
                    - {key for key, _ in columns} - panel.hidden_columns)]
                # Rows by the columns from left to right. Each search's rows stay together, also
                # when another search has the same text.
                shown.sort(key=lambda entry: [
                    (entry[1].get(key, "").casefold(), entry[1].get("alert_id", "") if key == "search_query" else "")
                    for key, _ in columns])
                body.update(columns=[{"key": key, "title": title} for key, title in (*columns, ("value", panel.value_title))],
                            rows=[{"labels": labels, "value": value} for _, labels, value in shown])
            else:
                body.update(style=panel.style, stacked=panel.stacked, series=[
                    {"legend": legend, "labels": labels, "values": values} for legend, labels, values in shown])
            if not sections or sections[-1]["title"] != panel.section:
                sections.append({"title": panel.section, "panels": []})
            sections[-1]["panels"].append(body)
        return {"enabled": True, "range": span, "ranges": list(RANGES), "start": collected["start"],
                "end": collected["end"], "step": collected["step"], "times": collected["times"],
                "warning": SEVERAL_BOTS if several else collected["warning"], "sections": sections}

    async def collect(self, span):
        """Every panel's series for a range, before they are limited to a server."""
        now = time.monotonic()
        entry = self.cache.get(span)
        if entry is None or entry[0] <= now:
            task = asyncio.create_task(self._collect(span))
            # Every waiter gets the error; this keeps asyncio quiet when all of them went away.
            task.add_done_callback(lambda task: task.cancelled() or task.exception())
            entry = self.cache[span] = (now + CACHE_SECONDS, task)
        try:
            return await asyncio.shield(entry[1])
        except Exception:
            # Only answers are kept; the next request after a failure asks again.
            if self.cache.get(span) is entry:
                del self.cache[span]
            raise

    async def _collect(self, span):
        seconds = RANGES[span]
        step = max(SCRAPE_SECONDS, seconds // POINTS)
        end = int(time.time()) // step * step
        start = end - seconds
        times = list(range(start, end + 1, step))
        answers = await asyncio.gather(*(self._answer(panel, start, end, step, seconds, len(times))
                                         for panel in self.panels))
        instances = set().union(*(found for _, _, found in answers))
        if len(instances) > 1:
            logger.warning("graphs_several_instances", extra={"fields": {"instances": sorted(instances)}})
        warning = None
        if not instances and not any(error for error, _, _ in answers):
            warning = ("Prometheus has no data about this bot in this range. The bot's operator can check that "
                       + ("PROMETHEUS_INSTANCE is this bot's instance label." if self.scoped else
                          "Prometheus scrapes the bot under the job auction-bot."))
        return {"start": start, "end": end, "step": step, "times": times, "instances": instances,
                "warning": warning,
                "panels": [(panel, error, series) for panel, (error, series, _) in zip(self.panels, answers)]}

    async def _answer(self, panel, start, end, step, seconds, points):
        """(error, series, instances) for a panel. A series is (legend, labels, values) for a
        graph and (legend, labels, value) for a table."""
        results = await asyncio.gather(*(
            self.prometheus.query(render(target.expr, self.instance, step, seconds),
                                  **({"time": end} if target.instant else {"start": start, "end": end, "step": step}))
            for target in panel.targets), return_exceptions=True)
        answers = []
        for result in results:
            if isinstance(result, GraphError):
                logger.warning("graph_query_failed", extra={"fields": {"panel_id": panel.id, "error": str(result)}})
                return str(result), [], set()
            if isinstance(result, BaseException):
                raise result
            answers.append(result)
        series, instances = [], set()
        for target, result in zip(panel.targets, answers):
            found = []
            for entry in result:
                metric = entry.get("metric") or {}
                if "instance" in metric:
                    instances.add(metric["instance"])
                labels = {name: value for name, value in metric.items() if name not in HIDDEN_LABELS}
                if target.instant:
                    found.append((target.legend, labels, number((entry.get("value") or [None, None])[1])))
                    continue
                values = [None] * points
                for moment, value in entry.get("values") or []:
                    index = round((float(moment) - start) / step)
                    if 0 <= index < points:
                        values[index] = number(value)
                found.append((target.legend, labels, values))
            # The same order on every refresh, so each line keeps its color.
            series += sorted(found, key=lambda entry: sorted(entry[1].items()))
        return None, series, instances
