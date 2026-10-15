"""Local operational commands for inspecting and retrying durable delivery jobs."""
import argparse
import json
import os
from pathlib import Path

import dotenv

from models import DeliveryJob, SCHEMA_VERSION, SchemaVersion, configure_database, database, utcnow


def main():
    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("DATABASE_URL", "alerts.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("outbox-list", help="List the latest pending or failed jobs")
    status.add_argument("--status", choices=("pending", "failed", "sent", "cancelled"), default="failed")
    status.add_argument("--limit", type=int, default=50)
    retry = commands.add_parser("outbox-retry", help="Retry failed jobs without losing acknowledged message IDs")
    scope = retry.add_mutually_exclusive_group(required=True)
    scope.add_argument("--id", type=int)
    scope.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.error("Database file does not exist; operational commands never create a database")
    if args.command == "outbox-list" and not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    configure_database(args.database)
    database.connect()
    try:
        version = SchemaVersion.get_or_none(SchemaVersion.id == 1) if "schema_version" in database.get_tables() else None
        if version is None or version.version != SCHEMA_VERSION:
            parser.error("Database must be migrated by the application before using operational commands")
        if args.command == "outbox-list":
            fields = (DeliveryJob.id, DeliveryJob.kind, DeliveryJob.status, DeliveryJob.attempts,
                      DeliveryJob.message_id, DeliveryJob.created_at, DeliveryJob.last_error)
            rows = DeliveryJob.select(*fields).where(DeliveryJob.status == args.status).order_by(DeliveryJob.id.desc()).limit(args.limit).dicts()
            print(json.dumps(list(rows), default=str, indent=2))
        else:
            query = DeliveryJob.update(status="pending", attempts=0, next_attempt_at=utcnow(), last_error=None)
            condition = DeliveryJob.status == "failed"
            if args.id is not None:
                condition &= DeliveryJob.id == args.id
            with database.atomic():
                count = query.where(condition).execute()
            print(json.dumps({"jobs_requeued": count}))
    finally:
        database.close()


if __name__ == "__main__":
    main()
