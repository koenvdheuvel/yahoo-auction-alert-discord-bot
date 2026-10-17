"""Filter previews and historical replay without live observation side effects."""
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import time

from domain import FilterRule
from filtering import CompiledRuleset, Decision, default_ruleset, validate_ruleset
from review_repository import POST_REMOVAL_DAYS, POST_REMOVAL_LIMIT, ReviewConflict, ReviewValidation


REPLAY_BUDGET_SECONDS = 10
# The reasons that make a listing filtered. A post to remove is shown with the first one.
BLOCKING_REASONS = frozenset({"source_excluded", "price_below_minimum", "price_above_maximum",
                              "excluded_group_match", "required_group_missing",
                              "legacy_blacklist_match", "legacy_whitelist_missing"})
SOURCES = frozenset({"yahooauction", "mercari", "surugaya"})


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


def _removal_days(value):
    if value is None or (isinstance(value, int) and not isinstance(value, bool) and value in POST_REMOVAL_DAYS):
        return value
    raise ReviewValidation("Choose posts from the last 7, 30 or 90 days, or all posts")


def _reason_key(reason):
    return f'{reason["code"]}:{reason.get("group_id") or reason["message"]}'


def _removable_json(post, reason):
    listing = post["listing"]
    return {"message_id": str(post["message_id"]), "posted_at": post["posted_at"], "title": listing["title"],
            "source": listing["source"], "external_id": listing["id"], "price": listing["price"],
            "image_url": listing["image_url"], "url": listing["url"], "reason": _reason_key(reason)}


def _replay_candidate(row):
    """The listing facts the replay view shows; the full snapshot stays in the archive."""
    payload = row.get("payload") or {}
    result = {key: row.get(key) for key in (
        "id", "source", "external_id", "title", "normalized_title", "observation_kind", "origin",
        "incomplete", "observed_at", "last_seen_at")}
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
        rows = await self.repository.replay_candidates(alert_id, limit=limit)
        result = await self._evaluate(self._replay, rows["items"], active_ruleset, draft, legacy)
        summary = result["summary"]
        summary.update(available=rows["available"], recent=rows["recent"])
        summary["truncated"] = summary["budget_exceeded"] or rows["available"] > rows["recent"]
        result["active_version_id"] = active["id"] if active else None
        return result

    @staticmethod
    def _replay(candidates, active_ruleset, draft_ruleset, legacy):
        active = CompiledRuleset(active_ruleset, legacy_rules=legacy)
        draft = CompiledRuleset(draft_ruleset, legacy_rules=legacy)
        summary = {"total": 0, "accepted": 0, "filtered": 0, "review": 0,
                   "newly_blocked": 0, "newly_allowed": 0, "unchanged": 0, "changed": 0,
                   "truncated": False, "budget_exceeded": False}
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

    @staticmethod
    def _sort_posts(posts, ruleset, legacy):
        """The posts whose listing these rules filter, and counts of the posts that stay.

        A post stays when its listing facts are incomplete, when a rule could not finish in
        time, when someone subscribed to it with 🔔, or when it is already queued for removal.
        """
        policy = CompiledRuleset(ruleset, legacy_rules=legacy)
        removable, kept = [], Counter()
        checked, deadline = 0, time.monotonic() + REPLAY_BUDGET_SECONDS
        for post in posts:
            if time.monotonic() >= deadline:
                break
            checked += 1
            listing = post["listing"]
            if post["queued"]:
                kept["queued"] += 1
                continue
            if listing["source"] not in SOURCES or not str(listing["title"] or "").strip():
                kept["incomplete"] += 1
                continue
            decision = policy.evaluate(listing)
            if decision.verdict != "filtered":
                kept["allowed" if decision.verdict == "accepted" else "review"] += 1
            elif any(reason["code"] in {"filter_timeout", "evaluation_budget"} for reason in decision.reasons):
                kept["unchecked"] += 1
            elif post["subscribed"]:
                kept["subscribed"] += 1
            else:
                reason = next((reason for reason in decision.reasons if reason["code"] in BLOCKING_REASONS),
                              decision.reasons[0])
                removable.append((post, reason))
        return {"removable": removable, "kept": kept, "checked": checked}

    async def post_removal_preview(self, alert_id, data):
        """Which of the search's posts the given rules, or else the published ones, filter. Nothing changes."""
        alert_id = identifier(alert_id, "alert_id")
        days = _removal_days(data.get("days", 30))
        posts = await self.repository.removable_posts(alert_id, days)
        active = posts["active_version"]
        draft = data.get("ruleset")
        ruleset = validate_ruleset(draft if draft is not None else active["ruleset"] if active else default_ruleset())
        legacy = _enabled_rules(await self.repository.review_filters(alert_id))
        result = await self._evaluate(self._sort_posts, posts["posts"], ruleset, legacy)
        run = result["removable"][:POST_REMOVAL_LIMIT]
        reasons = {}
        for _, reason in run:
            entry = reasons.setdefault(_reason_key(reason), {"key": _reason_key(reason), "message": reason["message"], "count": 0})
            entry["count"] += 1
        kept = result["kept"]
        return {"days": days, "posts_in_range": posts["total"], "checked": result["checked"],
                "partial": result["checked"] < posts["total"],
                "removable_total": len(result["removable"]), "limit": POST_REMOVAL_LIMIT,
                "posts": [_removable_json(post, reason) for post, reason in run],
                "reasons": sorted(reasons.values(), key=lambda entry: (-entry["count"], entry["message"])),
                "kept": {name: kept[name] for name in ("allowed", "review", "subscribed", "incomplete", "unchecked", "queued")},
                "channel_id": posts["channel_id"], "guild_id": posts["guild_id"],
                "active_version_id": active["id"] if active else None}

    async def remove_posts(self, alert_id, data):
        """Queue the removal of chosen posts. Each is checked against the published rules again first."""
        alert_id = identifier(alert_id, "alert_id")
        version_id = identifier(data.get("version_id"), "version_id")
        values = data.get("message_ids")
        if not isinstance(values, list) or not 1 <= len(values) <= POST_REMOVAL_LIMIT:
            raise ReviewValidation(f"Choose between 1 and {POST_REMOVAL_LIMIT} posts")
        message_ids = sorted({identifier(value, "message_id") for value in values})
        posts = await self.repository.removable_posts(alert_id, message_ids=message_ids, limit=POST_REMOVAL_LIMIT)
        active = posts["active_version"]
        if active is None or active["id"] != str(version_id):
            raise ReviewConflict("The published rules changed. Check the posts again.")
        legacy = _enabled_rules(await self.repository.review_filters(alert_id))
        result = await self._evaluate(self._sort_posts, posts["posts"], active["ruleset"], legacy)
        queued = await self.repository.queue_post_removals(
            alert_id, version_id, [post["message_id"] for post, _ in result["removable"]])
        return {"queued": queued, "skipped": len(message_ids) - queued}
