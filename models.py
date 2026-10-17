"""Versioned SQLite schema. Configuration and migration are explicit startup work."""
from datetime import datetime, timezone
from itertools import groupby
import logging
import os
from pathlib import Path
import sqlite3
import stat

from peewee import (BigIntegerField, BooleanField, CharField, DateTimeField,
                    ForeignKeyField, IntegerField, Model, SqliteDatabase, TextField)
from playhouse.sqlite_ext import AutoIncrementField

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 4
database = SqliteDatabase(None)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def configure_database(path):
    if not database.is_closed():
        database.close()
    database.init(path, pragmas={"foreign_keys": 1, "busy_timeout": 5000}, timeout=5)


class BaseModel(Model):
    class Meta:
        database = database


class Alert(BaseModel):
    channel_id = BigIntegerField(index=True)
    guild_id = BigIntegerField(null=True, index=True)
    search_query = CharField()

    class Meta:
        indexes = ((('channel_id', 'search_query'), True),)


class Item(BaseModel):
    item_id = CharField()
    checker = CharField()
    title = TextField(default="")
    stock = IntegerField(default=0)
    price = IntegerField(default=0)
    buyout_price = IntegerField(default=0)
    image_url = TextField(default="")
    url = TextField(default="")
    end_time = DateTimeField(null=True)
    muted = BooleanField(default=False)
    found_at = DateTimeField(default=utcnow)
    updated_at = DateTimeField(default=utcnow)
    last_seen_at = DateTimeField(default=utcnow)

    class Meta:
        indexes = ((('checker', 'item_id'), True),)


class AlertItem(BaseModel):
    alert = ForeignKeyField(Alert, backref="observations", on_delete="CASCADE")
    item = ForeignKeyField(Item, backref="observations", on_delete="CASCADE")
    stock = IntegerField()
    price = IntegerField()
    buyout_price = IntegerField()
    observed_at = DateTimeField(default=utcnow)

    class Meta:
        table_name = "alert_item"
        indexes = ((('alert', 'item'), True),)


class Message(BaseModel):
    message_id = BigIntegerField(primary_key=True)
    item = ForeignKeyField(Item, backref="messages", on_delete="CASCADE")
    alert = ForeignKeyField(Alert, null=True, on_delete="SET NULL")
    channel_id = BigIntegerField(index=True)
    deleted = BooleanField(default=False)
    created_at = DateTimeField(default=utcnow)


class Blacklist(BaseModel):
    item = ForeignKeyField(Item, backref="blacklists", on_delete="CASCADE")
    channel_id = BigIntegerField(index=True)

    class Meta:
        indexes = ((('item', 'channel_id'), True),)


class Notification(BaseModel):
    item = ForeignKeyField(Item, backref="notifications", on_delete="CASCADE")
    user_id = BigIntegerField(index=True)

    class Meta:
        indexes = ((('item', 'user_id'), True),)


class Filter(BaseModel):
    alert = ForeignKeyField(Alert, backref="filters", on_delete="CASCADE")
    method = CharField()
    type = CharField()
    value = TextField()
    enabled = BooleanField(default=True)
    matches = IntegerField(default=0)


class DeliveryJob(BaseModel):
    item = ForeignKeyField(Item, on_delete="CASCADE")
    alert = ForeignKeyField(Alert, null=True, on_delete="SET NULL")
    kind = CharField()
    destination_id = BigIntegerField()
    payload = TextField()
    status = CharField(default="pending", index=True)
    attempts = IntegerField(default=0)
    next_attempt_at = DateTimeField(default=utcnow, index=True)
    message_id = BigIntegerField(null=True)
    created_at = DateTimeField(default=utcnow)
    completed_at = DateTimeField(null=True)
    last_error = CharField(null=True)

    class Meta:
        table_name = "delivery_job"


class ReviewRuleVersion(BaseModel):
    """Rule payloads are append-only; alert identity remains after unregister."""
    id = AutoIncrementField()
    alert = ForeignKeyField(Alert, null=True, backref="review_versions", on_delete="SET NULL")
    alert_snapshot_id = IntegerField()
    channel_id = BigIntegerField()
    guild_id = BigIntegerField(null=True)
    search_query = CharField()
    version = IntegerField()
    ruleset = TextField()
    restored_from = ForeignKeyField("self", null=True, on_delete="SET NULL")
    created_at = DateTimeField(default=utcnow)

    class Meta:
        table_name = "review_rule_version"
        indexes = ((("alert", "version"), True),)


class ActiveReviewRules(BaseModel):
    alert = ForeignKeyField(Alert, primary_key=True, backref="active_review_rules", on_delete="CASCADE")
    version = ForeignKeyField(ReviewRuleVersion, on_delete="RESTRICT")
    updated_at = DateTimeField(default=utcnow)

    class Meta:
        table_name = "active_review_rules"


class CandidateObservation(BaseModel):
    """Archive facts and decisions independently of live Items and baselines.

    A row is one decision a listing received for an alert. When a later poll gives the same
    decision, the row's facts and `last_seen_at` are refreshed instead of adding a row, so
    `observed_at` is when this decision was first seen.
    """
    id = AutoIncrementField()
    alert = ForeignKeyField(Alert, null=True, backref="candidates", on_delete="SET NULL")
    alert_snapshot_id = IntegerField(null=True)
    channel_id = BigIntegerField()
    guild_id = BigIntegerField(null=True)
    search_query = CharField()
    source = CharField(index=True)
    external_id = CharField()
    title = TextField()
    normalized_title = TextField()
    payload = TextField()
    decision = TextField()
    verdict = CharField(index=True)
    normalization_version = IntegerField(null=True)
    ruleset_version = ForeignKeyField(ReviewRuleVersion, null=True, on_delete="SET NULL")
    observation_kind = CharField(default="listing")
    origin = CharField(default="live")
    incomplete = BooleanField(default=False)
    import_key = CharField(null=True, unique=True)
    observed_at = DateTimeField(default=utcnow, index=True)
    last_seen_at = DateTimeField(default=utcnow, index=True)

    class Meta:
        table_name = "candidate_observation"
        indexes = ((("alert", "observed_at"), False), (("alert", "source", "external_id"), False))


class SchemaVersion(BaseModel):
    version = IntegerField()

    class Meta:
        table_name = "schema_version"


REVIEW_TABLES = [ReviewRuleVersion, ActiveReviewRules, CandidateObservation]
TABLES = [Alert, Item, AlertItem, Message, Blacklist, Notification, Filter,
          DeliveryJob, *REVIEW_TABLES, SchemaVersion]
SOURCE_ALIASES = {"YahooAuctionsChecker": "yahooauction", "MercariChecker": "mercari",
                  "SurugayaChecker": "surugaya"}


def _backup():
    if database.database == ":memory:":
        return None
    path = Path(database.database)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(path.name + f".pre-v{SCHEMA_VERSION}.{timestamp}.bak")
    # The copy holds the same data, so it gets the database's permissions rather than the umask's.
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(path.stat().st_mode)))
    backup = sqlite3.connect(target)
    try:
        database.connection().backup(backup)
    finally:
        backup.close()
    return target


def _rows(table, existing):
    if table not in existing:
        return []
    cursor = database.execute_sql(f'SELECT * FROM "{table}"')
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _migrate_legacy(existing):
    if "item" in existing and "message_id" not in {c.name for c in database.get_columns("item")}:
        raise RuntimeError("Unrecognized unversioned database schema; migration stopped")
    backup = _backup()
    old = {name: _rows(name, existing) for name in ("alert", "item", "blacklist", "notification", "filter")}
    skipped = unknown_sources = disabled_filters = 0
    database.execute_sql("PRAGMA foreign_keys = OFF")
    try:
        with database.atomic():
            for name in ("notification", "blacklist", "filter", "item", "alert"):
                if name in existing:
                    database.execute_sql(f'DROP TABLE "{name}"')
            database.create_tables(TABLES)
            alert_ids = {row["id"] for row in old["alert"]}
            for row in old["alert"]:
                Alert.create(id=row["id"], channel_id=row["channel_id"], search_query=row["search_query"])
            item_ids = set()
            for row in old["item"]:
                source = SOURCE_ALIASES.get(row.get("checker"), row.get("checker") or "legacy")
                if source not in {"yahooauction", "mercari", "surugaya"}:
                    unknown_sources += 1
                item = Item.create(
                    id=row["id"], item_id=row["item_id"], checker=source,
                    title=row.get("title") or "", stock=row.get("stock") or 0,
                    price=row.get("price") or 0, buyout_price=row.get("buyout_price") or 0,
                    muted=bool(row.get("muted")), found_at=row.get("found_at") or utcnow(),
                    updated_at=row.get("updated_at") or utcnow(),
                )
                item_ids.add(item.id)
                alert_id = row.get("alert_id")
                if alert_id in alert_ids:
                    alert = Alert.get_by_id(alert_id)
                    AlertItem.create(alert=alert, item=item, stock=item.stock,
                                     price=item.price, buyout_price=item.buyout_price)
                    if row.get("message_id"):
                        Message.create(message_id=row["message_id"], item=item,
                                       alert=alert, channel_id=alert.channel_id)
            for row in old["blacklist"]:
                if row["item_id"] not in item_ids:
                    skipped += 1
                    continue
                Blacklist.insert(item=row["item_id"], channel_id=row["channel_id"]).on_conflict_ignore().execute()
            for row in old["notification"]:
                if row["item_id"] not in item_ids:
                    skipped += 1
                    continue
                Notification.insert(item=row["item_id"], user_id=int(row["user_id"])).on_conflict_ignore().execute()
            for row in old["filter"]:
                if row["alert_id"] not in alert_ids:
                    skipped += 1
                    continue
                method = row["type"] if row["type"] in {"regex", "text"} else "legacy"
                policy = "blacklist" if row.get("inverse") else "whitelist"
                if row["type"] in {"blacklist", "whitelist"}:
                    policy = row["type"]
                enabled = method != "legacy"
                disabled_filters += not enabled
                Filter.create(id=row["id"], alert=row["alert_id"], method=method, type=policy,
                              value=row["value"], enabled=enabled, matches=row.get("matches", 0))
            SchemaVersion.create(id=1, version=SCHEMA_VERSION)
            if database.execute_sql("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign key validation failed; migration rolled back")
    finally:
        database.execute_sql("PRAGMA foreign_keys = ON")
    logger.warning("database_migrated", extra={"fields": {
        "schema_version": SCHEMA_VERSION, "backup": str(backup) if backup else None,
        "orphan_rows_skipped": skipped, "unknown_source_items": unknown_sources,
        "disabled_legacy_filters": disabled_filters,
    }})


def _fold_repeated_snapshots():
    """Before v4 every poll archived another copy of each listing it saw.

    For each run of identical decisions on one listing, keep the last row and set its
    `observed_at` to the run's first sighting. Imported history stays as it is. Returns the
    number of removed rows.
    """
    rows = database.execute_sql(
        'SELECT "id", "alert_id", "source", "external_id", "decision", "observed_at" '
        "FROM \"candidate_observation\" WHERE \"origin\" = 'live' AND \"alert_id\" IS NOT NULL "
        "AND \"external_id\" != '' ORDER BY \"alert_id\", \"source\", \"external_id\", \"id\"").fetchall()
    removed, first_seen = [], []
    # The rows are sorted by listing, oldest first, so each group is one run of the same decision.
    for _, run in groupby(rows, key=lambda row: row[1:5]):
        *earlier, kept = run
        if earlier:
            removed.extend(row[0] for row in earlier)
            first_seen.append((earlier[0][5], kept[0]))
    connection = database.connection()
    connection.executemany('DELETE FROM "candidate_observation" WHERE "id" = ?', [(identifier,) for identifier in removed])
    connection.executemany('UPDATE "candidate_observation" SET "observed_at" = ? WHERE "id" = ?', first_seen)
    return len(removed)


def _upgrade(previous):
    """Bring a versioned database to SCHEMA_VERSION in one transaction, after a backup."""
    backup = _backup()
    details = {}
    with database.atomic():
        if previous == 2:
            # Rule version and archive tables did not exist yet, so they are created in their current shape.
            database.create_tables(REVIEW_TABLES)
        else:
            # SQLite needs a constant default to add a NOT NULL column. Every row is set next.
            database.execute_sql('ALTER TABLE "candidate_observation" ADD COLUMN "last_seen_at" '
                                 "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'")
            database.execute_sql('UPDATE "candidate_observation" SET "last_seen_at" = "observed_at"')
            # Nothing queried (source, external_id). Repeat sightings are matched per alert now.
            database.execute_sql('DROP INDEX IF EXISTS "candidateobservation_source_external_id"')
            CandidateObservation._schema.create_indexes(safe=True)
            # Filter Lab no longer has listing labels. The backup keeps them.
            labels = database.execute_sql('SELECT COUNT(*) FROM "candidate_feedback"').fetchone()[0]
            database.execute_sql('DROP TABLE IF EXISTS "candidate_feedback"')
            removed = _fold_repeated_snapshots()
            details.update(labels_removed=labels, repeated_snapshots_removed=removed)
        SchemaVersion.update(version=SCHEMA_VERSION).where(SchemaVersion.id == 1).execute()
        if database.execute_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign key validation failed; migration rolled back")
    logger.warning("database_migrated", extra={"fields": {
        "schema_version": SCHEMA_VERSION, "previous_version": previous,
        "backup": str(backup) if backup else None, **details,
    }})


def create_tables():
    database.connect(reuse_if_open=True)
    try:
        existing = set(database.get_tables())
        if "schema_version" in existing:
            version = SchemaVersion.get_by_id(1).version
            if version in {2, 3}:
                _upgrade(version)
            elif version != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported database schema version {version}")
        elif existing.intersection({"alert", "item", "filter", "notification", "blacklist"}):
            _migrate_legacy(existing)
        else:
            with database.atomic():
                database.create_tables(TABLES)
                SchemaVersion.create(id=1, version=SCHEMA_VERSION)
    finally:
        database.close()
