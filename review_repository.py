"""Candidate history, human feedback and append-only alert rule versions.

All methods run through the repository's existing dedicated SQLite executor.
History is independent of live listing/change baselines and delivery jobs.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from peewee import JOIN, fn

from models import (ActiveReviewRules, Alert, AlertItem, CandidateFeedback,
                    CandidateObservation, DeliveryJob, Item, ReviewRuleVersion,
                    database, utcnow)


FEEDBACK_LABELS = frozenset({"relevant", "wrong_product", "accessory", "bundle", "unsure"})
ORIGINS = frozenset({"live", "delivery_import", "item_import"})
MAX_JSON_BYTES = 128 * 1024
MAX_TITLE_LENGTH = 10000
MAX_VERSIONS_RETURNED = 30


class ReviewConflict(RuntimeError):
    """The active version changed since the caller loaded its draft."""


class ReviewNotFound(LookupError):
    """The requested live alert, candidate or version does not exist."""


class ReviewValidation(ValueError):
    """The request cannot be represented as bounded review data."""


def _identifier(value, name, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not (isinstance(value, int) or
                                     isinstance(value, str) and len(value) <= 19 and value.isdigit()):
        raise ReviewValidation(f"{name} must be a positive integer ID")
    result = int(value)
    if not 0 < result <= 2**63 - 1:
        raise ReviewValidation(f"{name} must be a positive integer ID")
    return result


def _bounded_integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ReviewValidation(f"{name} must be between {minimum} and {maximum}")
    return value


def _json_object(value, name, max_bytes=MAX_JSON_BYTES):
    if not isinstance(value, dict):
        raise ReviewValidation(f"{name} must be a JSON object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as error:
        raise ReviewValidation(f"{name} must contain JSON values") from error
    if max_bytes is not None and len(encoded.encode("utf-8")) > max_bytes:
        raise ReviewValidation(f"{name} exceeds 128 KiB")
    return encoded


def _capture_snapshot(value):
    """Bound an independent archive copy; never modify live listing facts."""
    original = _json_object(value, "payload", max_bytes=None)
    payload = json.loads(original)
    truncated = bool(payload.get("archive_truncated"))
    external_id = str(payload.get("id", payload.get("item_id", "")) or "")
    # Retain a distinguishable original identity even when the display ID is
    # clipped. Large IDs use a stable digest instead of filling the archive.
    if len(external_id) > 256:
        identity = {"sha256": hashlib.sha256(external_id.encode("utf-8")).hexdigest(),
                    "length": len(external_id)}
        if len(external_id.encode("utf-8")) <= 4096:
            identity["id"] = external_id
        payload["original_identity"] = identity
    for field, bound in (("title", MAX_TITLE_LENGTH), ("original_title", MAX_TITLE_LENGTH),
                         ("normalized_title", MAX_TITLE_LENGTH), ("id", 256), ("item_id", 256),
                         ("source", 64), ("url", 4096), ("image_url", 4096)):
        if field in {"id", "item_id", "source"} and field in payload and payload[field] is not None:
            payload[field] = str(payload[field])
        if isinstance(payload.get(field), str) and len(payload[field]) > bound:
            payload[field] = payload[field][:bound]
            truncated = True
    encoded = _json_object(payload, "payload", max_bytes=None)
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        truncated = True
        keep = {"id", "item_id", "source", "title", "original_title", "normalized_title", "stock",
                "price", "buyout_price", "image_url", "url", "end_time", "original_identity", "archive_truncated"}
        omitted = [key for key in payload if key not in keep]
        payload = {key: item for key, item in payload.items() if key in keep}
        if omitted:
            payload["archive_omitted_fields"] = [str(key)[:64] for key in omitted[:20]]
            payload["archive_omitted_field_count"] = len(omitted)
    if truncated:
        payload["archive_truncated"] = True
        payload["archive_payload_sha256"] = hashlib.sha256(original.encode("utf-8")).hexdigest()
        payload["archive_original_bytes"] = len(original.encode("utf-8"))
    encoded = _json_object(payload, "payload", max_bytes=None)
    # Several multibyte title copies can together exceed the byte budget even
    # though each fits its character bound. Reduce archive strings further as
    # needed, keeping canonical facts and identity metadata together.
    while len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        strings = [(key, item) for key, item in payload.items()
                   if isinstance(item, str) and len(item) > 128]
        if not strings:
            raise ReviewValidation("Payload cannot fit the bounded archive snapshot")
        key, item = max(strings, key=lambda pair: len(pair[1].encode("utf-8")))
        payload[key] = item[:len(item) // 2]
        encoded = _json_object(payload, "payload", max_bytes=None)
    return payload, _json_object(payload, "payload")


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _alert_json(alert, archived_count=None, active_version_id=None):
    result = {"id": str(alert.id), "channel_id": str(alert.channel_id),
              "guild_id": str(alert.guild_id) if alert.guild_id is not None else None,
              "search_query": alert.search_query}
    if archived_count is not None:
        result["archived_count"] = archived_count
        result["active_version_id"] = str(active_version_id) if active_version_id is not None else None
    return result


def _version_json(version):
    return {"id": str(version.id), "version": version.version,
            "alert_id": str(version.alert_id) if version.alert_id is not None else None,
            "alert_snapshot_id": str(version.alert_snapshot_id),
            "channel_id": str(version.channel_id),
            "guild_id": str(version.guild_id) if version.guild_id is not None else None,
            "search_query": version.search_query, "ruleset": json.loads(version.ruleset),
            "restored_from_version_id": str(version.restored_from_id) if version.restored_from_id else None,
            "created_at": _timestamp(version.created_at)}


def _candidate_json(row):
    decision = json.loads(row["decision"])
    return {"id": str(row["id"]), "alert_id": str(row["alert"]) if row["alert"] is not None else None,
            "alert_snapshot_id": str(row["alert_snapshot_id"]) if row["alert_snapshot_id"] is not None else None,
            "channel_id": str(row["channel_id"]),
            "guild_id": str(row["guild_id"]) if row["guild_id"] is not None else None,
            "search_query": row["search_query"], "source": row["source"], "external_id": row["external_id"],
            "title": row["title"], "original_title": row["title"], "normalized_title": row["normalized_title"],
            "payload": json.loads(row["payload"]), "decision": decision,
            "verdict": row["verdict"], "reasons": decision.get("reasons", []),
            "normalization_version": row["normalization_version"],
            "ruleset_version_id": str(row["ruleset_version"]) if row["ruleset_version"] is not None else None,
            "observation_kind": row["observation_kind"], "origin": row["origin"],
            "incomplete": bool(row["incomplete"]), "observed_at": _timestamp(row["observed_at"]),
            "feedback": row.get("feedback"), "feedback_updated_at": _timestamp(row.get("feedback_updated_at"))}


class ReviewRepositoryMixin:
    def _review_alert(self, alert_id):
        identifier = _identifier(alert_id, "alert_id")
        alert = Alert.get_or_none(Alert.id == identifier)
        if alert is None:
            raise ReviewNotFound("Alert no longer exists")
        return alert

    def _review_live_identity(self, alert_data):
        identifier = _identifier(alert_data.get("id"), "alert_id", nullable=True)
        channel = _identifier(alert_data.get("channel_id"), "channel_id")
        query = alert_data.get("search_query", "")
        if not isinstance(query, str) or len(query) > 256:
            raise ReviewValidation("search_query must contain at most 256 characters")
        return Alert.get_or_none(Alert.id == identifier, Alert.channel_id == channel,
                                 Alert.search_query == query) if identifier is not None else None

    def _review_current_version(self, alert):
        marker = ActiveReviewRules.get_or_none(ActiveReviewRules.alert == alert)
        if marker is None:
            return None
        version = marker.version
        if (version.alert_id != alert.id or version.channel_id != alert.channel_id
                or version.search_query != alert.search_query):
            raise ReviewValidation("Active rule version does not belong to this alert")
        return version

    async def review_alerts(self):
        def select():
            query = (Alert.select(Alert, fn.COUNT(CandidateObservation.id).alias("archived_count"),
                                  ActiveReviewRules.version.alias("active_version_id"))
                     .join(CandidateObservation, JOIN.LEFT_OUTER, on=CandidateObservation.alert == Alert.id)
                     .switch(Alert).join(ActiveReviewRules, JOIN.LEFT_OUTER, on=ActiveReviewRules.alert == Alert.id)
                     .group_by(Alert).order_by(Alert.channel_id, Alert.id))
            return [_alert_json(alert, alert.archived_count, alert.active_version_id) for alert in query.objects()]
        return await self._call("review_alerts", select)

    async def get_review_rules(self, alert_id):
        def select():
            alert = self._review_alert(alert_id)
            current = self._review_current_version(alert)
            query = ReviewRuleVersion.select().where(ReviewRuleVersion.alert == alert)
            total = query.count()
            versions = [_version_json(version) for version in
                        query.order_by(ReviewRuleVersion.version.desc()).limit(MAX_VERSIONS_RETURNED)]
            return {"alert": _alert_json(alert), "active_version": _version_json(current) if current else None,
                    "versions": versions, "versions_total": total}
        return await self._call("review_rules", select)

    async def active_rules_for_alert(self, alert_data):
        def select():
            alert = self._review_live_identity(alert_data)
            version = self._review_current_version(alert) if alert else None
            return _version_json(version) if version else None
        return await self._call("review_active_rules", select)

    def _archive_candidate_sync(self, alert_data, listing_payload, decision_payload,
                                ruleset_version_id=None, origin="live", *,
                                observed_at=None, import_key=None, incomplete=False):
        if not isinstance(origin, str) or origin not in ORIGINS:
            raise ReviewValidation("Unknown candidate origin")
        payload, encoded_payload = _capture_snapshot(listing_payload)
        encoded_decision = _json_object(decision_payload, "decision")
        decision = json.loads(encoded_decision)
        title = str(payload.get("original_title", payload.get("title", "")) or "")
        normalized_title = str(decision.get("normalized_title", payload.get("normalized_title", "")) or "")
        incomplete = (incomplete or bool(payload.get("archive_truncated"))
                      or len(title) > MAX_TITLE_LENGTH or len(normalized_title) > MAX_TITLE_LENGTH)
        version_id = _identifier(ruleset_version_id, "ruleset_version_id", nullable=True)
        snapshot_id = _identifier(alert_data.get("id"), "alert_id", nullable=True)
        channel = _identifier(alert_data.get("channel_id"), "channel_id")
        guild = _identifier(alert_data.get("guild_id"), "guild_id", nullable=True)
        query = alert_data.get("search_query", "")
        source = str(payload.get("source") or "")
        external_id = str(payload.get("id", payload.get("item_id", "")) or "")
        verdict = decision.get("verdict", "review")
        normalization_version = decision.get("normalization_version")
        if not isinstance(verdict, str) or verdict not in {"accepted", "filtered", "review"}:
            raise ReviewValidation("Unknown candidate verdict")
        if normalization_version is not None:
            _bounded_integer(normalization_version, "normalization_version", 0, 2**31 - 1)
        if not isinstance(decision.get("reasons", []), list):
            raise ReviewValidation("Decision reasons must be a list")
        if len(source) > 64 or len(external_id) > 256:
            raise ReviewValidation("Candidate source or external ID is too long")
        observation_kind = decision.get("observation_kind", "listing")
        if not isinstance(observation_kind, str) or len(observation_kind) > 64:
            raise ReviewValidation("observation_kind must contain at most 64 characters")
        with database.atomic():
            alert = self._review_live_identity(alert_data)
            if version_id is not None:
                version = ReviewRuleVersion.get_or_none(ReviewRuleVersion.id == version_id)
                if version is None:
                    raise ReviewNotFound("Rule version no longer exists")
                if (version.alert_snapshot_id != snapshot_id or version.channel_id != channel
                        or version.search_query != query):
                    raise ReviewValidation("Rule version does not belong to the candidate's alert")
                if alert is not None and version.alert_id != alert.id:
                    # An archived version also identifies the previous alert
                    # generation when SQLite has reused an identical live ID.
                    alert = None
            row = CandidateObservation.create(
                alert=alert, alert_snapshot_id=snapshot_id, channel_id=channel, guild_id=guild,
                search_query=query, source=source, external_id=external_id,
                title=title[:MAX_TITLE_LENGTH], normalized_title=normalized_title[:MAX_TITLE_LENGTH],
                payload=encoded_payload, decision=encoded_decision, verdict=verdict,
                normalization_version=normalization_version, ruleset_version=version_id,
                observation_kind=observation_kind, origin=origin, incomplete=incomplete,
                observed_at=observed_at or utcnow(), import_key=import_key,
            )
            return str(row.id)

    async def archive_candidate(self, alert_data, listing_payload, decision_payload,
                                ruleset_version_id=None, origin="live"):
        return await self._call("review_archive", self._archive_candidate_sync,
                                alert_data, listing_payload, decision_payload, ruleset_version_id, origin)

    def _review_candidates_query(self, alert_id=None, search="", source="", verdict="", feedback=""):
        query = (CandidateObservation.select(CandidateObservation, CandidateFeedback.label.alias("feedback"),
                                             CandidateFeedback.updated_at.alias("feedback_updated_at"))
                 .join(CandidateFeedback, JOIN.LEFT_OUTER,
                       on=CandidateFeedback.candidate == CandidateObservation.id))
        if alert_id is not None:
            alert = self._review_alert(alert_id)
            query = query.where(CandidateObservation.alert == alert,
                                CandidateObservation.channel_id == alert.channel_id,
                                CandidateObservation.search_query == alert.search_query)
        if not isinstance(search, str) or len(search) > 256:
            raise ReviewValidation("search must contain at most 256 characters")
        if search:
            query = query.where(CandidateObservation.title.contains(search)
                                | CandidateObservation.normalized_title.contains(search)
                                | CandidateObservation.external_id.contains(search)
                                | CandidateObservation.search_query.contains(search))
        if source:
            if not isinstance(source, str) or len(source) > 64:
                raise ReviewValidation("source must contain at most 64 characters")
            query = query.where(CandidateObservation.source == source)
        if verdict:
            if not isinstance(verdict, str) or verdict not in {"accepted", "filtered", "review"}:
                raise ReviewValidation("Unknown candidate verdict")
            query = query.where(CandidateObservation.verdict == verdict)
        if feedback:
            if not isinstance(feedback, str):
                raise ReviewValidation("Unknown feedback label")
            if feedback in {"unreviewed", "unlabeled"}:
                query = query.where(CandidateFeedback.candidate.is_null())
            elif feedback in FEEDBACK_LABELS:
                query = query.where(CandidateFeedback.label == feedback)
            else:
                raise ReviewValidation("Unknown feedback label")
        return query

    async def list_candidates(self, alert_id=None, search="", source="", verdict="", feedback="", limit=50, offset=0):
        _bounded_integer(limit, "limit", 1, 500)
        _bounded_integer(offset, "offset", 0, 10000000)
        def select():
            query = self._review_candidates_query(alert_id, search, source, verdict, feedback)
            total = query.count()
            items = [_candidate_json(row) for row in query.order_by(
                CandidateObservation.observed_at.desc(), CandidateObservation.id.desc()).limit(limit).offset(offset).dicts()]
            return {"items": items, "total": total, "limit": limit, "offset": offset,
                    "has_more": offset + len(items) < total,
                    "next_offset": offset + len(items) if offset + len(items) < total else None}
        return await self._call("review_candidates", select)

    async def review_candidates(self, alert_id, limit=500, offset=0):
        return await self.list_candidates(alert_id=alert_id, limit=limit, offset=offset)

    async def set_candidate_feedback(self, candidate_id, label):
        identifier = _identifier(candidate_id, "candidate_id")
        if label is not None and (not isinstance(label, str) or label not in FEEDBACK_LABELS):
            raise ReviewValidation("Unknown feedback label")
        def update():
            with database.atomic():
                if not CandidateObservation.select().where(CandidateObservation.id == identifier).exists():
                    raise ReviewNotFound("Candidate no longer exists")
                if label is None:
                    CandidateFeedback.delete().where(CandidateFeedback.candidate == identifier).execute()
                else:
                    CandidateFeedback.insert(candidate=identifier, label=label, updated_at=utcnow()).on_conflict(
                        conflict_target=[CandidateFeedback.candidate],
                        update={CandidateFeedback.label: label, CandidateFeedback.updated_at: utcnow()}).execute()
                row = self._review_candidates_query().where(CandidateObservation.id == identifier).dicts().get()
                return _candidate_json(row)
        return await self._call("review_feedback", update)

    def _publish_review_rules_sync(self, alert_id, ruleset, expected_version_id, restored_from_id=None):
        encoded = _json_object(ruleset, "ruleset")
        expected = _identifier(expected_version_id, "expected_version_id", nullable=True)
        with database.atomic("IMMEDIATE"):
            alert = self._review_alert(alert_id)
            current = self._review_current_version(alert)
            if (current.id if current else None) != expected:
                raise ReviewConflict("Active rules changed; reload before publishing")
            maximum = ReviewRuleVersion.select(fn.MAX(ReviewRuleVersion.version)).where(
                ReviewRuleVersion.alert == alert).scalar() or 0
            version = ReviewRuleVersion.create(
                alert=alert, alert_snapshot_id=alert.id, channel_id=alert.channel_id,
                guild_id=alert.guild_id, search_query=alert.search_query, version=maximum + 1,
                ruleset=encoded, restored_from=restored_from_id,
            )
            if current:
                changed = ActiveReviewRules.update(version=version, updated_at=utcnow()).where(
                    ActiveReviewRules.alert == alert, ActiveReviewRules.version == current).execute()
                if changed != 1:
                    raise ReviewConflict("Active rules changed; reload before publishing")
            else:
                ActiveReviewRules.create(alert=alert, version=version)
            return _version_json(version)

    async def publish_review_rules(self, alert_id, ruleset, expected_version_id=None):
        return await self._call("review_publish", self._publish_review_rules_sync,
                                alert_id, ruleset, expected_version_id)

    async def activate_review_version(self, alert_id, version_id, expected_version_id):
        identifier = _identifier(version_id, "version_id")
        def activate():
            alert = self._review_alert(alert_id)
            version = ReviewRuleVersion.get_or_none(ReviewRuleVersion.id == identifier, ReviewRuleVersion.alert == alert)
            if version is None or version.channel_id != alert.channel_id or version.search_query != alert.search_query:
                raise ReviewNotFound("Rule version does not belong to this live alert")
            return self._publish_review_rules_sync(alert.id, json.loads(version.ruleset), expected_version_id, version.id)
        return await self._call("review_activate", activate)

    async def prune_candidates(self, days=90, max_rows=50000, limit=1000):
        _bounded_integer(days, "days", 1, 36500)
        _bounded_integer(limit, "limit", 1, 1000)
        if max_rows is not None:
            _bounded_integer(max_rows, "max_rows", 0, 10000000)
        def prune():
            with database.atomic():
                cutoff = utcnow() - timedelta(days=days)
                ordered = CandidateObservation.select(CandidateObservation.id).order_by(
                    CandidateObservation.observed_at, CandidateObservation.id)
                ids = [row.id for row in ordered.where(CandidateObservation.observed_at < cutoff).limit(limit)]
                count = CandidateObservation.select().count()
                excess = max(0, count - len(ids) - max_rows) if max_rows is not None else 0
                if excess and len(ids) < limit:
                    query = ordered.where(CandidateObservation.id.not_in(ids)) if ids else ordered
                    ids.extend(row.id for row in query.limit(min(excess, limit - len(ids))))
                deleted = CandidateObservation.delete().where(CandidateObservation.id.in_(ids)).execute() if ids else 0
                remaining = count - deleted
                more = CandidateObservation.select().where(CandidateObservation.observed_at < cutoff).exists()
                more = more or (max_rows is not None and remaining > max_rows)
                return {"deleted": deleted, "remaining": remaining, "has_more": more}
        return await self._call("review_prune", prune)

    async def bootstrap_history(self, limit=1000):
        """Import recent available snapshots explicitly, never at startup.

        Current item rows and channel-job snapshots cannot reconstruct omitted
        or filtered listings or their original policy decisions. Imported rows
        remain review/incomplete; normalization uses current default settings.
        """
        from normalization import NORMALIZATION_VERSION, normalize_title

        _bounded_integer(limit, "limit", 1, 1000)
        def bootstrap():
            jobs = list(DeliveryJob.select().where(DeliveryJob.kind == "channel").order_by(
                DeliveryJob.created_at.desc(), DeliveryJob.id.desc()).limit(limit + 1))
            observations = list(AlertItem.select(AlertItem, Item, Alert).join(Item).switch(AlertItem).join(Alert)
                                .order_by(AlertItem.observed_at.desc(), AlertItem.id.desc()).limit(limit + 1))
            available = [(job.created_at, "delivery_import", job) for job in jobs]
            available += [(row.observed_at, "item_import", row) for row in observations]
            available.sort(key=lambda value: (value[0], value[1], value[2].id), reverse=True)
            counts = {"imported": 0, "delivery_import": 0, "item_import": 0,
                      "skipped": 0, "incomplete": 0, "truncated": len(available) > limit}
            with database.atomic():
                for observed, origin, row in available[:limit]:
                    key = f"{origin}:{row.id}:{_timestamp(observed)}"
                    if CandidateObservation.select().where(CandidateObservation.import_key == key).exists():
                        counts["skipped"] += 1
                        continue
                    if origin == "delivery_import":
                        try:
                            snapshot = json.loads(row.payload)
                            payload = snapshot["listing"]
                            if not isinstance(payload, dict):
                                raise ValueError("Invalid listing payload")
                        except (ValueError, TypeError, KeyError):
                            counts["skipped"] += 1
                            continue
                        alert = Alert.get_or_none(Alert.id == row.alert_id) if row.alert_id else None
                        data = {"id": row.alert_id, "channel_id": row.destination_id,
                                "guild_id": alert.guild_id if alert else None,
                                "search_query": str(snapshot.get("search_query") or "")[:256]}
                    else:
                        item, alert = row.item, row.alert
                        payload = {"id": item.item_id, "source": item.checker, "title": item.title,
                                   "stock": row.stock, "price": row.price, "buyout_price": row.buyout_price,
                                   "image_url": item.image_url, "url": item.url, "end_time": _timestamp(item.end_time)}
                        data = {"id": alert.id, "channel_id": alert.channel_id, "guild_id": alert.guild_id,
                                "search_query": alert.search_query}
                    reasons = [{"code": "import_incomplete",
                                "message": "Original policy decision is unavailable; title uses current normalization defaults."}]
                    try:
                        normalized_title = normalize_title(str(payload.get("title") or ""))
                    except ValueError:
                        normalized_title = ""
                        reasons.append({"code": "normalization_error",
                                        "message": "Imported title exceeds current normalization limits."})
                    decision = {"verdict": "review", "allowed": False, "normalized_title": normalized_title,
                                "reasons": reasons, "matched_groups": [], "legacy_matched_rules": [],
                                "normalization_version": NORMALIZATION_VERSION}
                    try:
                        self._archive_candidate_sync(data, payload, decision, origin=origin,
                                                     observed_at=observed, import_key=key, incomplete=True)
                    except ReviewValidation:
                        counts["skipped"] += 1
                        continue
                    counts["imported"] += 1
                    counts[origin] += 1
                    counts["incomplete"] += 1
            return counts
        return await self._call("review_bootstrap", bootstrap)
