"""Operational commands never create/migrate databases or replay sent jobs."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from models import (
    DeliveryJob, Item, SCHEMA_VERSION, SchemaVersion, TABLES,
    configure_database, database,
)


ROOT = Path(__file__).resolve().parents[1]


class ManageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "bot.sqlite"

    def create_schema(self, version=SCHEMA_VERSION, with_version_row=True):
        configure_database(str(self.path))
        database.connect()
        try:
            database.create_tables(TABLES)
            if with_version_row:
                SchemaVersion.create(id=1, version=version)
            item = Item.create(item_id="auction", checker="yahooauction", title="vinyl")
            rows = (
                ("failed", 777), ("failed", None), ("sent", 888),
                ("pending", None), ("cancelled", 999),
            )
            for status, message_id in rows:
                DeliveryJob.create(
                    item=item, kind="channel", destination_id=10,
                    payload=json.dumps({"listing": {"id": "auction"}}),
                    status=status, attempts=4, message_id=message_id,
                    last_error="ForbiddenError" if status == "failed" else None,
                )
        finally:
            database.close()

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, str(ROOT / "manage.py"), "--database", str(self.path), *arguments],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )

    def rows(self):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM delivery_job ORDER BY id")]

    def test_list_defaults_to_failed_jobs_and_respects_order_and_limit(self):
        self.create_schema()
        result = self.invoke("outbox-list", "--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 2)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["attempts"], 4)
        self.assertEqual(rows[0]["last_error"], "ForbiddenError")
        self.assertEqual([row["status"] for row in self.rows()],
                         ["failed", "failed", "sent", "pending", "cancelled"])

    def test_list_can_inspect_acknowledged_sent_jobs(self):
        self.create_schema()
        result = self.invoke("outbox-list", "--status", "sent")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual([(row["id"], row["message_id"]) for row in rows], [(3, 888)])

    def test_retry_one_failed_job_preserves_its_acknowledged_message(self):
        self.create_schema()
        before = self.rows()
        result = self.invoke("outbox-retry", "--id", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"jobs_requeued": 1})
        rows = self.rows()
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["attempts"], 0)
        self.assertIsNone(rows[0]["last_error"])
        self.assertEqual(rows[0]["message_id"], 777)
        self.assertEqual(rows[0]["payload"], before[0]["payload"])
        self.assertEqual(rows[1:], before[1:])

    def test_retry_all_only_requeues_failed_jobs(self):
        self.create_schema()
        before = self.rows()
        result = self.invoke("outbox-retry", "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"jobs_requeued": 2})
        rows = self.rows()
        self.assertEqual([row["status"] for row in rows],
                         ["pending", "pending", "sent", "pending", "cancelled"])
        self.assertEqual([row["message_id"] for row in rows], [777, None, 888, None, 999])
        self.assertEqual(rows[2:], before[2:])

    def test_retry_never_replays_sent_cancelled_or_unknown_jobs(self):
        self.create_schema()
        before = self.rows()
        for job_id in (3, 5, 999):
            with self.subTest(job_id=job_id):
                result = self.invoke("outbox-retry", "--id", str(job_id))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"jobs_requeued": 0})
        self.assertEqual(self.rows(), before)

    def test_retry_requires_explicit_id_or_all_and_rejects_both(self):
        self.create_schema()
        before = self.rows()
        for arguments in (("outbox-retry",), ("outbox-retry", "--id", "1", "--all")):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, 2)
        self.assertEqual(self.rows(), before)

    def test_list_limit_validation_never_changes_the_database(self):
        self.create_schema()
        before = self.rows()
        for limit in ("0", "-1", "1001"):
            with self.subTest(limit=limit):
                result = self.invoke("outbox-list", "--limit", limit)
                self.assertEqual(result.returncode, 2)
                self.assertIn("--limit must be between 1 and 1000", result.stderr)
        self.assertEqual(self.rows(), before)

    def test_missing_database_is_refused_without_creating_it(self):
        result = self.invoke("outbox-list")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Database file does not exist", result.stderr)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_unversioned_legacy_database_is_refused_without_migration(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE legacy_marker (value TEXT)")
            connection.execute("INSERT INTO legacy_marker VALUES ('preserve me')")
        result = self.invoke("outbox-list")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be migrated", result.stderr)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT value FROM legacy_marker").fetchone()[0],
                             "preserve me")
            self.assertEqual(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            ).fetchall(), [("legacy_marker",)])
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_empty_schema_version_table_is_refused_without_changes(self):
        self.create_schema(with_version_row=False)
        before = self.rows()
        result = self.invoke("outbox-retry", "--all")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be migrated", result.stderr)
        self.assertEqual(self.rows(), before)

    def test_outdated_schema_is_refused_without_upgrading_or_backup(self):
        self.create_schema(version=SCHEMA_VERSION - 1)
        before = self.rows()
        result = self.invoke("outbox-retry", "--all")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be migrated", result.stderr)
        self.assertEqual(self.rows(), before)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_version").fetchone()[0],
                             SCHEMA_VERSION - 1)
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])
