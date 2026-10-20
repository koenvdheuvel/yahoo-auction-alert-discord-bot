"""Ingestion orchestrates provider facts, pure policy and transactional persistence."""
from collections import Counter
import asyncio
import logging

from filtering import CompiledRuleset, Decision, default_ruleset
from normalization import NORMALIZATION_VERSION, normalize_title
from providers import ProviderError

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


class Ingestion:
    def __init__(self, repository, metrics, settings):
        self.repository, self.metrics, self.settings = repository, metrics, settings

    @staticmethod
    def _special_decision(listing, code, message, verdict="review", normalization=None):
        title = listing.get("title", "") if isinstance(listing, dict) else listing.title
        try:
            normalized = normalize_title(title, normalization)
        except ValueError:
            normalized = ""
        return Decision(verdict, normalized, [{"code": code, "message": message}], []).payload()

    @staticmethod
    def _invalid_snapshot(raw, source):
        raw = raw if isinstance(raw, dict) else {}
        title = raw.get("title")
        return {"id": str(raw.get("id") or "")[:256], "source": source,
                "title": title[:10000] if isinstance(title, str) else "",
                "price": None, "stock": None, "normalization_version": NORMALIZATION_VERSION}

    async def _archive(self, alert, listing, decision, version_id, kind="listing"):
        payload = listing if isinstance(listing, dict) else listing.payload()
        payload = dict(payload)
        decision = {**decision, "observation_kind": kind}
        await self.repository.archive_candidate(alert, payload, decision, version_id)

    async def check(self, provider, alert, *, seeding=False):
        """seeding: the search has no baseline on this marketplace yet, because it was just turned on
        or is new to the bot. Its listings are saved without being posted, so later checks post only
        listings that are new from then on."""
        version = await self.repository.active_rules_for_alert(alert)
        version_id = version["id"] if version else None
        policy = CompiledRuleset(version["ruleset"] if version else default_ruleset(),
                                 await self.repository.filters_for_alert(alert["id"]))
        normalization = policy.ruleset["normalization"]
        matched = Counter()
        invalid = 0
        try:
            async for raw in provider.iter_items(alert["search_query"]):
                try:
                    listing = provider.normalize(raw)
                except (ValueError, TypeError, KeyError, ProviderError):
                    invalid += 1
                    self.metrics.items.labels(source=provider.source, outcome="invalid").inc()
                    logger.exception("listing_normalization_failed")
                    snapshot = self._invalid_snapshot(raw, provider.source)
                    await self._archive(alert, snapshot, self._special_decision(
                        snapshot, "invalid_listing", "The provider returned invalid listing facts.",
                        normalization=normalization),
                        version_id, "invalid")
                    continue
                if await self.repository.is_blacklisted(provider.source, listing.id, alert["channel_id"]):
                    self.metrics.items.labels(source=provider.source, outcome="blacklisted").inc()
                    await self._archive(alert, listing, self._special_decision(
                        listing, "channel_blacklist", "This listing is excluded in this channel.", "filtered",
                        normalization=normalization),
                        version_id, "blacklisted")
                    continue
                # Live ingestion and replay share the same bounded pure evaluator.
                decision = await asyncio.to_thread(policy.evaluate, listing) if policy.has_regex else policy.evaluate(listing)
                evaluation_failed = any(reason["code"] in {"filter_timeout", "evaluation_budget"}
                                        for reason in decision.reasons)
                if evaluation_failed:
                    invalid += 1
                    self.metrics.items.labels(source=provider.source, outcome="filter_timeout").inc()
                    logger.warning("filter_evaluation_timed_out", extra={"fields": {
                        "item_id": listing.id, "ruleset_version_id": version_id}})
                matched.update(decision.legacy_matched_rules)
                if not decision.allowed:
                    await self._archive(alert, listing, decision.payload(), version_id)
                    if not evaluation_failed:
                        self.metrics.items.labels(source=provider.source, outcome=decision.verdict).inc()
                    continue
                outcome = await self.repository.observe(alert, listing, self.settings.price_threshold,
                                                        decision_payload=decision.payload(),
                                                        ruleset_version_id=version_id, post=not seeding)
                self.metrics.items.labels(source=provider.source, outcome=outcome).inc()
        finally:
            await self.repository.record_filter_matches(matched)
        if seeding:
            # Every page was read. A listing that failed to parse is not part of the baseline, as
            # in any check; staying unseeded would keep the search from ever posting.
            await self.repository.mark_seeded(alert, provider.source)
            logger.info("alert_source_seeded")
        if invalid:
            raise IngestionError(f"Check completed with {invalid} invalid listings")
