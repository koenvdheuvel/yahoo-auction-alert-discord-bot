"""Filter previews and historical replay without live observation side effects."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

from domain import FilterRule
from filtering import CompiledRuleset, Decision, default_ruleset, validate_ruleset
from review_repository import JUDGED_LABELS, ReviewValidation


# Labeled listings outside the recent sample that replay still checks.
REPLAY_LABELED_LIMIT = 1000
REPLAY_BUDGET_SECONDS = 10


class ReviewBusy(Exception):
    pass


def identifier(value, name="id", optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise ReviewValidation(f"{name} must be a positive integer")
    result = int(value)
    if not 1 <= result <= 2 ** 63 - 1:
        raise ReviewValidation(f"{name} is outside its allowed range")
    return result


def _enabled_rules(filters):
    """Discord filters that take part in evaluation, as the live checker loads them."""
    return [FilterRule(row["id"], row["method"], row["policy"], row["value"]) for row in filters if row["enabled"]]


def _replay_candidate(row):
    """The listing facts the replay view shows; the full snapshot stays in the archive."""
    payload = row.get("payload") or {}
    result = {key: row.get(key) for key in (
        "id", "source", "external_id", "title", "normalized_title", "observation_kind", "origin",
        "incomplete", "observed_at", "last_seen_at", "feedback")}
    result.update({key: payload.get(key) for key in ("price", "url", "image_url")})
    return result


class ReviewService:
    """One bounded CPU worker; database access remains on its own executor."""

    def __init__(self, repository, replay_limit=500):
        self.repository = repository
        self.replay_limit = replay_limit
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="filter-review")
        self.busy = asyncio.Lock()
        self.closed = False

    async def close(self):
        if self.closed:
            return
        self.closed = True
        # Evaluation checks deadlines and every pattern is independently bounded.
        await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)

    async def _evaluate(self, function, *args):
        if self.closed or self.busy.locked():
            raise ReviewBusy("Another preview or replay is running. Try again in a moment.")
        async with self.busy:
            future = asyncio.get_running_loop().run_in_executor(self.executor, function, *args)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                # Settle owned work before releasing the lock or closing resources.
                await future
                raise

    async def rules(self, alert_id):
        alert_id = identifier(alert_id, "alert_id")
        result = await self.repository.get_review_rules(alert_id)
        result["legacy_filters"] = await self.repository.review_filters(alert_id)
        result["default_ruleset"] = default_ruleset()
        return result

    @staticmethod
    def validate(data):
        return {"ruleset": validate_ruleset(data.get("ruleset"))}

    async def preview(self, data):
        ruleset = validate_ruleset(data.get("ruleset", default_ruleset()))
        title = data.get("title", "")
        if not isinstance(title, str):
            raise ReviewValidation("Title must be text")
        source = data.get("source", "yahooauction")
        if not isinstance(source, str) or source not in {"yahooauction", "mercari", "surugaya"}:
            raise ReviewValidation("Select a supported source")
        price = data.get("price", 0)
        stock = data.get("stock", 1)
        for name, value in (("price", price), ("stock", stock)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10 ** 12:
                raise ReviewValidation(f"{name} must be a nonnegative integer")
        legacy = []
        if data.get("alert_id") is not None:
            legacy = _enabled_rules(await self.repository.review_filters(identifier(data["alert_id"], "alert_id")))
        policy = CompiledRuleset(ruleset, legacy_rules=legacy)
        listing = {"title": title, "source": source, "price": price, "stock": stock}
        decision = await self._evaluate(policy.evaluate, listing)
        return {"decision": decision.payload()}

    async def replay(self, data):
        alert_id = identifier(data.get("alert_id"), "alert_id")
        limit = data.get("limit", self.replay_limit)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.replay_limit:
            raise ReviewValidation(f"Replay limit must be between 1 and {self.replay_limit}")
        draft = validate_ruleset(data.get("ruleset", default_ruleset()))
        state = await self.repository.get_review_rules(alert_id)
        active = state["active_version"]
        active_ruleset = active["ruleset"] if active else default_ruleset()
        legacy = _enabled_rules(await self.repository.review_filters(alert_id))
        rows = await self.repository.replay_candidates(alert_id, limit=limit, labeled_limit=REPLAY_LABELED_LIMIT)
        result = await self._evaluate(self._replay, rows["items"], active_ruleset, draft, legacy)
        summary = result["summary"]
        summary.update(available=rows["available"], recent=rows["recent"], labeled_extra=rows["labeled_extra"])
        summary["truncated"] = summary["budget_exceeded"] or rows["available"] > rows["recent"]
        result["active_version_id"] = active["id"] if active else None
        return result

    @staticmethod
    def _replay(candidates, active_ruleset, draft_ruleset, legacy):
        active = CompiledRuleset(active_ruleset, legacy_rules=legacy)
        draft = CompiledRuleset(draft_ruleset, legacy_rules=legacy)
        summary = {"total": 0, "accepted": 0, "filtered": 0, "review": 0,
                   "newly_blocked": 0, "newly_allowed": 0, "unchanged": 0, "changed": 0,
                   "truncated": False, "budget_exceeded": False, "labeled": 0, "unwanted_allowed": 0,
                   "relevant_blocked": 0, "relevant_allowed": 0,
                   "unwanted_blocked": 0, "relevant_review": 0, "unwanted_review": 0}
        items, deadline = [], time.monotonic() + REPLAY_BUDGET_SECONDS
        for row in candidates:
            if time.monotonic() >= deadline:
                summary["truncated"] = summary["budget_exceeded"] = True
                break
            payload = row.get("payload", row.get("listing", {}))
            if row.get("observation_kind") == "blacklisted":
                blocked = Decision("filtered", row.get("normalized_title", ""), [{
                    "code": "channel_blacklist", "message":
                    "This snapshot was excluded in its channel; its recorded blacklist still vetoes replay."}], []).payload()
                current, proposed = blocked, blocked
            # "enrichment_error" rows predate FromJapan-sourced Surugaya titles; no longer written.
            elif row.get("observation_kind") in {"invalid", "enrichment_error"} or payload.get("archive_truncated"):
                incomplete = Decision("review", row.get("normalized_title", ""), [{
                    "code": "incomplete_snapshot", "message":
                    "This snapshot has missing or truncated listing facts and needs review."}], []).payload()
                current, proposed = incomplete, incomplete
            else:
                current, proposed = active.evaluate(payload).payload(), draft.evaluate(payload).payload()
            before, after = current["verdict"], proposed["verdict"]
            change = "unchanged" if before == after else (
                "newly_allowed" if after == "accepted" else
                "newly_blocked" if before == "accepted" and after == "filtered" else "changed")
            summary["total"] += 1
            summary[after] += 1
            summary[change] += 1
            label = row.get("feedback")
            if label in JUDGED_LABELS:
                summary["labeled"] += 1
                prefix = "relevant" if label == "relevant" else "unwanted"
                suffix = {"accepted": "allowed", "filtered": "blocked", "review": "review"}[after]
                summary[prefix + "_" + suffix] += 1
            items.append({"candidate": _replay_candidate(row), "original_decision": row["decision"],
                          "active_decision": current, "draft_decision": proposed, "change": change})
        return {"items": items, "summary": summary}

    async def publish(self, alert_id, data):
        ruleset = validate_ruleset(data.get("ruleset"))
        if "expected_version_id" not in data:
            raise ReviewValidation("Reload the active version before publishing")
        expected = identifier(data["expected_version_id"], "expected_version_id", optional=True)
        return await self.repository.publish_review_rules(identifier(alert_id), ruleset, expected)

    async def rollback(self, alert_id, data):
        if "expected_version_id" not in data:
            raise ReviewValidation("Reload the active version before restoring")
        expected = identifier(data["expected_version_id"], "expected_version_id", optional=True)
        return await self.repository.activate_review_version(
            identifier(alert_id), identifier(data.get("version_id"), "version_id"), expected)
