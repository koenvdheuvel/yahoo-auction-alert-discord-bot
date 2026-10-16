"""Candidate history, human feedback and append-only alert rule versions.

All methods run through the repository's existing dedicated SQLite executor.
History is independent of live listing/change baselines and delivery jobs.
"""
import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import json

from peewee import JOIN, Case, chunked, fn

from domain import discord_time, first_discord_id_at
from models import (ActiveReviewRules, Alert, AlertItem, CandidateFeedback,
                    CandidateObservation, DeliveryJob, Filter, Item, Message, Notification,
                    ReviewRuleVersion, database, utcnow)


FEEDBACK_LABELS = frozenset({"relevant", "wrong_product", "accessory", "bundle", "unsure"})
# Labels that say whether a listing belongs in the alert; "unsure" says neither.
JUDGED_LABELS = FEEDBACK_LABELS - {"unsure"}
VERDICTS = ("accepted", "filtered", "review")
ORIGINS = frozenset({"live", "delivery_import", "item_import"})
MAX_JSON_BYTES = 128 * 1024
MAX_TITLE_LENGTH = 10000
MAX_VERSIONS_RETURNED = 30
MAX_FEEDBACK_BATCH = 200
# Removing a search's Discord posts that its published rules filter. Ages count back from
# now in days (None is all time); one run removes at most POST_REMOVAL_LIMIT posts.
POST_REMOVAL_DAYS = (7, 30, 90, None)
POST_REMOVAL_LIMIT = 1000
POST_REMOVAL_SCAN_LIMIT = 20000


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


def _feedback_label(label):
    if label is not None and (not isinstance(label, str) or label not in FEEDBACK_LABELS):
        raise ReviewValidation("Unknown feedback label")
    return label


def _counts(query, column, keys):
    """Row counts per value of column, with zero for values that have no rows."""
    counts = dict.fromkeys(keys, 0)
    for value, count in query.select(column, fn.COUNT(CandidateObservation.id)).group_by(column).tuples():
        counts["unlabeled" if value is None else value] = count
    return counts


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


def _alert_json(alert, stats=None, active_version_id=None):
    result = {"id": str(alert.id), "channel_id": str(alert.channel_id),
              "guild_id": str(alert.guild_id) if alert.guild_id is not None else None,
              "search_query": alert.search_query}
    if stats is not None:
        result.update(stats)
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


def _encode_cursor(row):
    """An opaque position after this row in newest-first order."""
    text = f'{_timestamp(row["observed_at"])}|{row["id"]}'
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _decode_cursor(cursor):
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 128:
        raise ReviewValidation("The page cursor is invalid; reload the list")
    try:
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        observed, identifier = text.split("|")
        observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            raise ValueError("A cursor time includes its time zone")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ReviewValidation("The page cursor is invalid; reload the list") from None
    return observed_at.astimezone(timezone.utc).replace(tzinfo=None), _identifier(identifier, "cursor")


def _latest_condition(alert=None):
    """Keep the newest row of each listing per alert; older rows hold decisions it no longer gets.

    Rows without an alert or a listing ID cannot be matched to later sightings, so they count
    as their own latest row.
    """
    newest = CandidateObservation.alias()
    latest = newest.select(fn.MAX(newest.id)).where(newest.alert.is_null(False), newest.external_id != "")
    if alert is not None:
        latest = latest.where(newest.alert == alert)
    latest = latest.group_by(newest.alert, newest.source, newest.external_id)
    return (CandidateObservation.id.in_(latest) | CandidateObservation.alert.is_null()
            | (CandidateObservation.external_id == ""))


def _in_guilds(guilds):
    """Rows that belong to these servers: their alerts' rows, and detached rows saved there.

    A row with an alert belongs to the alert's server. Unregistering an alert detaches its rows,
    which keep the server they were saved in. Rows of alerts without a server match no server.
    """
    alerts = Alert.select(Alert.id).where(Alert.guild_id.in_(guilds))
    return (CandidateObservation.alert.in_(alerts)
            | (CandidateObservation.alert.is_null() & CandidateObservation.guild_id.in_(guilds)))


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
            "last_seen_at": _timestamp(row.get("last_seen_at")),
            "feedback": row.get("feedback"), "feedback_updated_at": _timestamp(row.get("feedback_updated_at"))}


class ReviewRepositoryMixin:
    """Methods behind the dashboard take `guilds`: the server IDs the person may see, or None for all.

    An alert, candidate or version outside those servers is reported exactly like a missing one.
    """

    def _review_alert(self, alert_id, guilds=None):
        identifier = _identifier(alert_id, "alert_id")
        alert = Alert.get_or_none(Alert.id == identifier)
        if alert is None or (guilds is not None and alert.guild_id not in guilds):
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

    async def review_alerts(self, guilds=None):
        """Alerts with counts over each listing's latest decision, plus archive totals per server."""
        def select():
            archived = dict(CandidateObservation.select(CandidateObservation.alert, fn.COUNT(CandidateObservation.id))
                            .where(CandidateObservation.alert.is_null(False))
                            .group_by(CandidateObservation.alert).tuples())
            # Rows detached from an unregistered alert, counted per server they were saved in.
            detached = dict(CandidateObservation.select(CandidateObservation.guild_id, fn.COUNT(CandidateObservation.id))
                            .where(CandidateObservation.alert.is_null())
                            .group_by(CandidateObservation.guild_id).tuples())
            if guilds is not None:
                detached = {guild: count for guild, count in detached.items() if guild in guilds}
            counts = [fn.SUM(Case(None, [(CandidateObservation.verdict == verdict, 1)], 0)) for verdict in VERDICTS]
            latest = (CandidateObservation
                      .select(CandidateObservation.alert, fn.COUNT(CandidateObservation.id), *counts,
                              fn.COUNT(CandidateFeedback.candidate), fn.MAX(CandidateObservation.last_seen_at))
                      .join(CandidateFeedback, JOIN.LEFT_OUTER, on=CandidateFeedback.candidate == CandidateObservation.id)
                      .where(CandidateObservation.alert.is_null(False), _latest_condition())
                      .group_by(CandidateObservation.alert).tuples())
            stats = {row[0]: row[1:] for row in latest}
            active = dict(ActiveReviewRules.select(ActiveReviewRules.alert, ActiveReviewRules.version).tuples())
            query = Alert.select().order_by(Alert.channel_id, Alert.id)
            if guilds is not None:
                query = query.where(Alert.guild_id.in_(guilds))
            alerts, servers = [], {}
            for alert in query:
                listings, accepted, filtered, review, labeled, last_seen = stats.get(alert.id, (0, 0, 0, 0, 0, None))
                alerts.append(_alert_json(alert, {
                    "archived_count": archived.get(alert.id, 0), "listing_count": listings,
                    "accepted_count": accepted, "filtered_count": filtered, "review_count": review,
                    "labeled_count": labeled, "last_seen_at": _timestamp(last_seen),
                }, active.get(alert.id)))
                if alert.guild_id is not None:
                    servers[alert.guild_id] = servers.get(alert.guild_id, 0) + archived.get(alert.id, 0)
            for guild, count in detached.items():
                if guild is not None:
                    servers[guild] = servers.get(guild, 0) + count
            by_guild = {str(guild): {"archived_count": count, "unassigned_count": detached.get(guild, 0)}
                        for guild, count in servers.items()}
            unassigned = sum(detached.values())
            return {"alerts": alerts, "totals": {
                "archived_count": sum(alert["archived_count"] for alert in alerts) + unassigned,
                "unassigned_count": unassigned, "guilds": by_guild}}
        return await self._call("review_alerts", select)

    async def review_filters(self, alert_id, guilds=None):
        """Every Discord filter on the alert, including disabled ones, for display."""
        def select():
            alert = self._review_alert(alert_id, guilds)
            return [{"id": row.id, "method": row.method, "policy": row.type, "value": row.value,
                     "enabled": row.enabled, "matches": row.matches}
                    for row in Filter.select().where(Filter.alert == alert).order_by(Filter.id)]
        return await self._call("review_filters", select)

    async def get_review_rules(self, alert_id, guilds=None):
        def select():
            alert = self._review_alert(alert_id, guilds)
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
            now = observed_at or utcnow()
            if (origin != "live" and alert is not None and external_id and CandidateObservation.select().where(
                    CandidateObservation.alert == alert, CandidateObservation.source == source,
                    CandidateObservation.external_id == external_id).exists()):
                # Imports carry no decision. A copy of a listing the search already has would
                # replace the bot's real decision as the newest row, so it is skipped.
                return None
            previous = None
            if origin == "live" and alert is not None and external_id:
                previous = (CandidateObservation
                            .select(CandidateObservation.id, CandidateObservation.decision,
                                    CandidateObservation.observation_kind, CandidateObservation.origin)
                            .where(CandidateObservation.alert == alert, CandidateObservation.source == source,
                                   CandidateObservation.external_id == external_id)
                            .order_by(CandidateObservation.id.desc()).first())
                if (previous is not None and previous.origin == "live" and previous.decision == encoded_decision
                        and previous.observation_kind == observation_kind):
                    # Each poll sees most listings again. The same decision refreshes the
                    # latest facts on the existing row instead of archiving another copy.
                    CandidateObservation.update(
                        guild_id=guild, title=title[:MAX_TITLE_LENGTH], payload=encoded_payload,
                        ruleset_version=version_id, incomplete=incomplete, last_seen_at=now,
                    ).where(CandidateObservation.id == previous.id).execute()
                    return str(previous.id)
            row = CandidateObservation.create(
                alert=alert, alert_snapshot_id=snapshot_id, channel_id=channel, guild_id=guild,
                search_query=query, source=source, external_id=external_id,
                title=title[:MAX_TITLE_LENGTH], normalized_title=normalized_title[:MAX_TITLE_LENGTH],
                payload=encoded_payload, decision=encoded_decision, verdict=verdict,
                normalization_version=normalization_version, ruleset_version=version_id,
                observation_kind=observation_kind, origin=origin, incomplete=incomplete,
                observed_at=now, last_seen_at=now, import_key=import_key,
            )
            if previous is not None:
                # A label describes the listing, so it stays with the listing when its decision changes.
                label = CandidateFeedback.get_or_none(CandidateFeedback.candidate == previous.id)
                if label is not None:
                    CandidateFeedback.create(candidate=row.id, label=label.label, updated_at=label.updated_at)
            return str(row.id)

    async def archive_candidate(self, alert_data, listing_payload, decision_payload,
                                ruleset_version_id=None, origin="live"):
        return await self._call("review_archive", self._archive_candidate_sync,
                                alert_data, listing_payload, decision_payload, ruleset_version_id, origin)

    def _review_candidates_query(self, alert_id=None, search="", source="", verdict="", feedback="",
                                 latest=False, guilds=None, guild_id=None):
        query = (CandidateObservation.select(CandidateObservation, CandidateFeedback.label.alias("feedback"),
                                             CandidateFeedback.updated_at.alias("feedback_updated_at"))
                 .join(CandidateFeedback, JOIN.LEFT_OUTER,
                       on=CandidateFeedback.candidate == CandidateObservation.id))
        if guilds is not None:
            query = query.where(_in_guilds(guilds))
        if guild_id is not None:
            guild_id = _identifier(guild_id, "guild_id")
            if guilds is not None and guild_id not in guilds:
                raise ReviewNotFound("Server not found")
            query = query.where(_in_guilds([guild_id]))
        alert = None
        if alert_id is not None:
            alert = self._review_alert(alert_id, guilds)
            query = query.where(CandidateObservation.alert == alert,
                                CandidateObservation.channel_id == alert.channel_id,
                                CandidateObservation.search_query == alert.search_query)
        if latest:
            query = query.where(_latest_condition(alert))
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

    async def list_candidates(self, alert_id=None, search="", source="", verdict="", feedback="", limit=50,
                              offset=0, cursor=None, latest=False, facets=False, guilds=None, guild_id=None):
        """Newest first. A cursor continues after the last row of the previous page, so labeling
        rows or new polls between pages neither skip nor repeat rows; offset remains available."""
        _bounded_integer(limit, "limit", 1, 500)
        _bounded_integer(offset, "offset", 0, 10000000)
        position = _decode_cursor(cursor) if cursor is not None else None

        def select():
            def scoped(**changes):
                filters = {"search": search, "source": source, "verdict": verdict, "feedback": feedback}
                return self._review_candidates_query(alert_id, latest=latest, guilds=guilds, guild_id=guild_id,
                                                     **{**filters, **changes})

            query = scoped()
            page = query.order_by(CandidateObservation.observed_at.desc(), CandidateObservation.id.desc())
            if position is not None:
                observed, identifier = position
                page = page.where((CandidateObservation.observed_at < observed) | (
                    (CandidateObservation.observed_at == observed) & (CandidateObservation.id < identifier)))
            else:
                page = page.offset(offset)
            rows = list(page.limit(limit + 1).dicts())
            more = len(rows) > limit
            items = [_candidate_json(row) for row in rows[:limit]]
            result = {"items": items, "total": query.count(), "limit": limit, "offset": offset,
                      "has_more": more, "next_offset": offset + len(items) if more and position is None else None,
                      "next_cursor": _encode_cursor(rows[limit - 1]) if more else None}
            if facets:
                # Each facet counts what selecting one of its values would show.
                result["facets"] = {
                    "verdict": _counts(scoped(verdict=""), CandidateObservation.verdict, VERDICTS),
                    "feedback": _counts(scoped(feedback=""), CandidateFeedback.label,
                                        ("unlabeled", *sorted(FEEDBACK_LABELS)))}
            return result
        return await self._call("review_candidates", select)

    async def replay_candidates(self, alert_id, limit=500, labeled_limit=1000, guilds=None):
        """The latest decision of the most recently seen listings, then labeled listings beyond them."""
        _bounded_integer(limit, "limit", 1, 500)
        _bounded_integer(labeled_limit, "labeled_limit", 0, 5000)

        def select():
            query = self._review_candidates_query(alert_id, latest=True, guilds=guilds)
            ordered = query.order_by(CandidateObservation.last_seen_at.desc(), CandidateObservation.id.desc())
            recent = list(ordered.limit(limit).dicts())
            seen = {row["id"] for row in recent}
            extra = []
            if labeled_limit:
                labeled = ordered.where(CandidateFeedback.label.in_(JUDGED_LABELS)).limit(labeled_limit + len(seen))
                extra = [row for row in labeled.dicts() if row["id"] not in seen][:labeled_limit]
            return {"items": [_candidate_json(row) for row in recent + extra], "available": query.count(),
                    "recent": len(recent), "labeled_extra": len(extra)}
        return await self._call("review_replay_candidates", select)

    def _write_feedback(self, identifiers, label, guilds=None):
        """Set or clear labels on the candidates that still exist and return their IDs."""
        query = CandidateObservation.select(CandidateObservation.id).where(CandidateObservation.id.in_(identifiers))
        if guilds is not None:
            query = query.where(_in_guilds(guilds))
        existing = [row.id for row in query]
        if existing and label is None:
            CandidateFeedback.delete().where(CandidateFeedback.candidate.in_(existing)).execute()
        elif existing:
            now = utcnow()
            CandidateFeedback.insert_many([{"candidate": identifier, "label": label, "updated_at": now}
                                           for identifier in existing]).on_conflict(
                conflict_target=[CandidateFeedback.candidate],
                update={CandidateFeedback.label: label, CandidateFeedback.updated_at: now}).execute()
        return existing

    async def set_candidate_feedback(self, candidate_id, label, guilds=None):
        identifier = _identifier(candidate_id, "candidate_id")
        _feedback_label(label)
        def update():
            with database.atomic():
                if not self._write_feedback([identifier], label, guilds):
                    raise ReviewNotFound("Candidate no longer exists")
                row = self._review_candidates_query().where(CandidateObservation.id == identifier).dicts().get()
                return _candidate_json(row)
        return await self._call("review_feedback", update)

    async def set_candidates_feedback(self, candidate_ids, label, guilds=None):
        """Label several candidates at once. Candidates removed by retention are reported, not fatal."""
        if not isinstance(candidate_ids, list) or not 1 <= len(candidate_ids) <= MAX_FEEDBACK_BATCH:
            raise ReviewValidation(f"Select between 1 and {MAX_FEEDBACK_BATCH} listings")
        identifiers = list(dict.fromkeys(_identifier(value, "candidate_id") for value in candidate_ids))
        _feedback_label(label)
        def update():
            with database.atomic():
                existing = self._write_feedback(identifiers, label, guilds)
                rows = self._review_candidates_query().where(CandidateObservation.id.in_(existing)).dicts()
                items = {row["id"]: _candidate_json(row) for row in rows} if existing else {}
                return {"items": [items[identifier] for identifier in identifiers if identifier in items],
                        "missing": [str(identifier) for identifier in identifiers if identifier not in items]}
        return await self._call("review_feedback_bulk", update)

    def _publish_review_rules_sync(self, alert_id, ruleset, expected_version_id, restored_from_id=None,
                                   guilds=None):
        encoded = _json_object(ruleset, "ruleset")
        expected = _identifier(expected_version_id, "expected_version_id", nullable=True)
        with database.atomic("IMMEDIATE"):
            alert = self._review_alert(alert_id, guilds)
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

    async def publish_review_rules(self, alert_id, ruleset, expected_version_id=None, guilds=None):
        return await self._call("review_publish", self._publish_review_rules_sync,
                                alert_id, ruleset, expected_version_id, None, guilds)

    async def activate_review_version(self, alert_id, version_id, expected_version_id, guilds=None):
        identifier = _identifier(version_id, "version_id")
        def activate():
            alert = self._review_alert(alert_id, guilds)
            version = ReviewRuleVersion.get_or_none(ReviewRuleVersion.id == identifier, ReviewRuleVersion.alert == alert)
            if version is None or version.channel_id != alert.channel_id or version.search_query != alert.search_query:
                raise ReviewNotFound("Rule version does not belong to this live alert")
            return self._publish_review_rules_sync(alert.id, json.loads(version.ruleset), expected_version_id,
                                                   version.id, guilds)
        return await self._call("review_activate", activate)

    async def prune_candidates(self, days=90, max_rows=50000, limit=1000):
        """Remove the rows seen least recently, by age first and then down to max_rows.

        Labeled rows are kept: they are the examples replay measures drafts against, and
        clearing a label lets retention remove the row again.
        """
        _bounded_integer(days, "days", 1, 36500)
        _bounded_integer(limit, "limit", 1, 1000)
        if max_rows is not None:
            _bounded_integer(max_rows, "max_rows", 0, 10000000)
        def prune():
            with database.atomic():
                cutoff = utcnow() - timedelta(days=days)
                unlabeled = (CandidateObservation.select(CandidateObservation.id)
                             .join(CandidateFeedback, JOIN.LEFT_OUTER,
                                   on=CandidateFeedback.candidate == CandidateObservation.id)
                             .where(CandidateFeedback.candidate.is_null()))
                ordered = unlabeled.order_by(CandidateObservation.last_seen_at, CandidateObservation.id)
                ids = [row.id for row in ordered.where(CandidateObservation.last_seen_at < cutoff).limit(limit)]
                count = CandidateObservation.select().count()
                excess = max(0, count - len(ids) - max_rows) if max_rows is not None else 0
                if excess and len(ids) < limit:
                    query = ordered.where(CandidateObservation.id.not_in(ids)) if ids else ordered
                    ids.extend(row.id for row in query.limit(min(excess, limit - len(ids))))
                deleted = CandidateObservation.delete().where(CandidateObservation.id.in_(ids)).execute() if ids else 0
                remaining = count - deleted
                more = unlabeled.where(CandidateObservation.last_seen_at < cutoff).exists()
                if not more and max_rows is not None and remaining > max_rows:
                    more = unlabeled.exists()
                return {"deleted": deleted, "remaining": remaining, "has_more": more}
        return await self._call("review_prune", prune)

    async def bootstrap_history(self, limit=1000, guilds=None):
        """Import recent available snapshots explicitly, never at startup.

        Current item rows and channel-job snapshots cannot reconstruct omitted
        or filtered listings or their original policy decisions. Imported rows
        remain review/incomplete; normalization uses current default settings.
        Listings the alert already has are skipped, including a listing that
        was both posted and tracked.
        """
        from normalization import NORMALIZATION_VERSION, normalize_title

        _bounded_integer(limit, "limit", 1, 1000)
        def bootstrap():
            jobs = DeliveryJob.select().where(DeliveryJob.kind == "channel")
            observations = AlertItem.select(AlertItem, Item, Alert).join(Item).switch(AlertItem).join(Alert)
            if guilds is not None:
                # Only the person's servers. Jobs of unregistered alerts have no server to check.
                scoped = Alert.select(Alert.id).where(Alert.guild_id.in_(guilds))
                jobs = jobs.where(DeliveryJob.alert.in_(scoped))
                observations = observations.where(AlertItem.alert.in_(scoped))
            jobs = list(jobs.order_by(DeliveryJob.created_at.desc(), DeliveryJob.id.desc()).limit(limit + 1))
            observations = list(observations.order_by(AlertItem.observed_at.desc(), AlertItem.id.desc())
                                .limit(limit + 1))
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
                        archived = self._archive_candidate_sync(data, payload, decision, origin=origin,
                                                                observed_at=observed, import_key=key, incomplete=True)
                    except ReviewValidation:
                        archived = None
                    if archived is None:
                        counts["skipped"] += 1
                        continue
                    counts["imported"] += 1
                    counts[origin] += 1
                    counts["incomplete"] += 1
            return counts
        return await self._call("review_bootstrap", bootstrap)

    async def removable_posts(self, alert_id, days=None, message_ids=None, limit=POST_REMOVAL_SCAN_LIMIT,
                              guilds=None):
        """The search's live posts in its channel, newest first, with the listing facts they show.

        Ages come from the message IDs. Converting an old database dated every earlier post
        to the conversion, so the saved creation time cannot tell how old a post is.
        """
        _bounded_integer(limit, "limit", 1, POST_REMOVAL_SCAN_LIMIT)
        if days not in POST_REMOVAL_DAYS:
            raise ReviewValidation("Choose posts from the last 7, 30 or 90 days, or all posts")

        def select():
            alert = self._review_alert(alert_id, guilds)
            version = self._review_current_version(alert)
            subscribed = Notification.select(Notification.item)
            queued = DeliveryJob.select(DeliveryJob.message_id).where(
                DeliveryJob.kind == "delete", DeliveryJob.status == "pending", DeliveryJob.message_id.is_null(False))
            query = (Message
                     .select(Message.message_id, Item.item_id, Item.checker, Item.title, Item.price, Item.stock,
                             Item.buyout_price, Item.image_url, Item.url,
                             Case(None, [(Message.item.in_(subscribed), 1)], 0).alias("subscribed"),
                             Case(None, [(Message.message_id.in_(queued), 1)], 0).alias("queued"))
                     .join(Item)
                     .where(Message.alert == alert, Message.channel_id == alert.channel_id, ~Message.deleted))
            if days is not None:
                query = query.where(Message.message_id >= first_discord_id_at(utcnow() - timedelta(days=days)))
            if message_ids is not None:
                query = query.where(Message.message_id.in_(message_ids))
            rows = list(query.order_by(Message.message_id.desc()).limit(limit).dicts())
            posts = [{
                "message_id": row["message_id"], "posted_at": _timestamp(discord_time(row["message_id"])),
                "subscribed": bool(row["subscribed"]), "queued": bool(row["queued"]),
                "listing": {"id": row["item_id"], "source": row["checker"], "title": row["title"],
                            "price": row["price"], "stock": row["stock"], "buyout_price": row["buyout_price"],
                            "image_url": row["image_url"], "url": row["url"]},
            } for row in rows]
            return {"posts": posts, "total": query.count() if len(rows) >= limit else len(rows),
                    "channel_id": str(alert.channel_id),
                    "guild_id": str(alert.guild_id) if alert.guild_id is not None else None,
                    "active_version": _version_json(version) if version else None}
        return await self._call("review_removable_posts", select)

    async def queue_post_removals(self, alert_id, version_id, message_ids, guilds=None):
        """Queue the deletion of posts that the published version filters, for the delivery worker.

        Returns how many were queued. Posts that are gone, got a 🔔 subscriber or are already
        queued are skipped. Queued posts of the same listings are cancelled, so they do not
        come back. All jobs of one run share their creation time, which identifies the run.
        """
        def queue():
            with database.atomic("IMMEDIATE"):
                alert = self._review_alert(alert_id, guilds)
                current = self._review_current_version(alert)
                if current is None or current.id != version_id:
                    raise ReviewConflict("The published rules changed. Check the posts again.")
                if not message_ids:
                    return 0
                queued = DeliveryJob.select(DeliveryJob.message_id).where(
                    DeliveryJob.kind == "delete", DeliveryJob.status == "pending", DeliveryJob.message_id.is_null(False))
                rows = list(Message.select(Message.message_id, Message.item).where(
                    Message.message_id.in_(message_ids), Message.alert == alert,
                    Message.channel_id == alert.channel_id, ~Message.deleted,
                    Message.item.not_in(Notification.select(Notification.item)),
                    Message.message_id.not_in(queued)).tuples())
                now = utcnow()
                payload = json.dumps({"version_id": str(version_id)})
                for batch in chunked(rows, 100):
                    DeliveryJob.insert_many([
                        {"item": item_id, "alert": alert.id, "kind": "delete", "destination_id": alert.channel_id,
                         "message_id": message_id, "payload": payload, "created_at": now, "next_attempt_at": now}
                        for message_id, item_id in batch]).execute()
                for batch in chunked(sorted({item_id for _, item_id in rows}), 500):
                    DeliveryJob.update(status="cancelled").where(
                        DeliveryJob.item.in_(batch), DeliveryJob.alert == alert, DeliveryJob.kind == "channel",
                        DeliveryJob.destination_id == alert.channel_id,
                        DeliveryJob.status.in_(("pending", "failed"))).execute()
                return len(rows)
        return await self._call("review_queue_post_removals", queue)

    async def post_removal_status(self, alert_id, guilds=None):
        """Progress of the search's newest removal run."""
        def select():
            alert = self._review_alert(alert_id, guilds)
            removals = DeliveryJob.select().where(DeliveryJob.alert == alert, DeliveryJob.kind == "delete")
            latest = removals.select(fn.MAX(DeliveryJob.created_at)).scalar()
            if latest is None:
                return {"run": None}
            counts = dict(removals.select(DeliveryJob.status, fn.COUNT(DeliveryJob.id))
                          .where(DeliveryJob.created_at == latest).group_by(DeliveryJob.status).tuples())
            return {"run": {"queued_at": _timestamp(latest), "total": sum(counts.values()),
                            "pending": counts.get("pending", 0), "removed": counts.get("sent", 0),
                            "failed": counts.get("failed", 0), "cancelled": counts.get("cancelled", 0)}}
        return await self._call("review_post_removal_status", select)
