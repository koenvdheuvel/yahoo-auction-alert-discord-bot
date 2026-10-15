"""Validated configuration; environment loading belongs to the entry point."""
from dataclasses import dataclass, field
import os


def boolean(name, default=True):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1", "yes"}


def positive(name, default, minimum=1, maximum=None):
    value = int(os.getenv(name, str(default)))
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range")
    return value


@dataclass(frozen=True)
class Settings:
    token: str = field(default="", repr=False)
    database_path: str = "alerts.db"
    interval: int = 1800
    concurrency: int = 4
    check_timeout: int = 600
    request_timeout: int = 30
    request_retries: int = 2
    max_pages: int = 100
    delivery_attempts: int = 8
    monitoring_enabled: bool = True
    monitoring_host: str = "127.0.0.1"
    monitoring_port: int = 9100
    metrics_stats_interval: int = 10
    health_max_poll_age: int = 2460
    price_threshold: int = 500
    enabled_sources: tuple = ("yahooauction", "mercari", "surugaya")
    log_level: str = "INFO"
    review_enabled: bool = True
    review_host: str = "127.0.0.1"
    review_port: int = 9101
    review_token: str = field(default="", repr=False)
    review_token_file: str = ""
    review_replay_limit: int = 500
    history_retention_days: int = 90
    history_max_rows: int = 50000

    @classmethod
    def from_env(cls, require_token=True):
        token = os.getenv("BOT_TOKEN", "").strip()
        if require_token and not token:
            raise ValueError("BOT_TOKEN is required")
        database_path = os.getenv("DATABASE_URL", "alerts.db")
        if not database_path or "://" in database_path:
            raise ValueError("DATABASE_URL must be a SQLite filename, not a URL")
        interval = positive("CHECK_INTERVAL", 1800)
        timeout = positive("CHECK_TIMEOUT", 600)
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL is invalid")
        sources = tuple(source for source, flag in (
            ("yahooauction", "ENABLE_YAHOO_AUCTION"),
            ("mercari", "ENABLE_MERCARI"),
            ("surugaya", "ENABLE_SURUGAYA"),
        ) if boolean(flag))
        return cls(
            token=token, database_path=database_path, interval=interval,
            concurrency=positive("CHECK_CONCURRENCY", 4, maximum=32),
            check_timeout=timeout, request_timeout=positive("REQUEST_TIMEOUT", 30),
            request_retries=positive("REQUEST_RETRIES", 2, minimum=0, maximum=5),
            max_pages=positive("MAX_SEARCH_PAGES", 100),
            delivery_attempts=positive("DELIVERY_MAX_ATTEMPTS", 8),
            monitoring_enabled=boolean("MONITORING_ENABLED"),
            monitoring_host=os.getenv("MONITORING_HOST", "127.0.0.1"),
            monitoring_port=positive("MONITORING_PORT", 9100, maximum=65535),
            metrics_stats_interval=positive("METRICS_STATS_INTERVAL", 10),
            health_max_poll_age=positive("HEALTH_MAX_POLL_AGE", interval + timeout + 60),
            price_threshold=positive("PRICE_CHANGE_THRESHOLD", 500, minimum=0),
            enabled_sources=sources, log_level=log_level,
            review_enabled=boolean("REVIEW_ENABLED"),
            review_host=os.getenv("REVIEW_HOST", "127.0.0.1"),
            review_port=positive("REVIEW_PORT", 9101, maximum=65535),
            review_token=os.getenv("REVIEW_TOKEN", "").strip(),
            review_token_file=os.getenv("REVIEW_TOKEN_FILE", ""),
            review_replay_limit=positive("REVIEW_REPLAY_LIMIT", 500, maximum=500),
            history_retention_days=positive("HISTORY_RETENTION_DAYS", 90, maximum=3650),
            history_max_rows=positive("HISTORY_MAX_ROWS", 50000, maximum=1000000),
        )
