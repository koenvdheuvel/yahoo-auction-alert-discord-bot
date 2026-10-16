"""Validated configuration; environment loading belongs to the entry point."""
from dataclasses import dataclass, field
import os
import stat
from urllib.parse import urlsplit


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


def secret(name):
    """A value from NAME, or from the file that NAME_FILE names, but not both."""
    value = os.getenv(name, "").strip()
    path = os.getenv(name + "_FILE", "").strip()
    if value and path:
        raise ValueError(f"Set {name} or {name}_FILE, not both")
    if not path:
        return value
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise ValueError(f"{name}_FILE must name a regular file")
        with open(path, encoding="utf-8") as handle:
            return handle.read(4096).strip()
    except OSError as error:
        raise ValueError(f"{name}_FILE cannot be read: {error.strerror}") from None


def public_url(value):
    """The address people open the dashboard at. Discord sends them back to it after sign-in."""
    value = value.strip()
    if not value:
        return ""
    parts = urlsplit(value)
    try:
        parts.port
    except ValueError:
        raise ValueError("DASHBOARD_PUBLIC_URL has an invalid port") from None
    # Plain http leaks the session cookie, so it is only accepted on this computer.
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or parts.scheme not in {"https", "http"} or (parts.scheme == "http" and not local):
        raise ValueError("DASHBOARD_PUBLIC_URL must start with https:// (http:// only works for localhost)")
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("DASHBOARD_PUBLIC_URL must be the site address only, such as https://dashboard.example.com")
    # Browsers leave the default port out of the Host header, so it is left out here too.
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    default = {"https": 443, "http": 80}[parts.scheme]
    port = f":{parts.port}" if parts.port not in {None, default} else ""
    return f"{parts.scheme}://{host}{port}"


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
    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 9101
    dashboard_token: str = field(default="", repr=False)
    dashboard_token_file: str = ""
    # Discord sign-in is on when the client secret is set. The client ID is the bot's application ID.
    dashboard_public_url: str = ""
    dashboard_discord_client_secret: str = field(default="", repr=False)
    dashboard_replay_limit: int = 500
    history_retention_days: int = 90
    history_max_rows: int = 50000

    @property
    def discord_sign_in(self):
        return bool(self.dashboard_discord_client_secret)

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
        dashboard_token = os.getenv("DASHBOARD_TOKEN", "").strip()
        dashboard_token_file = os.getenv("DASHBOARD_TOKEN_FILE", "")
        review_url = public_url(os.getenv("DASHBOARD_PUBLIC_URL", ""))
        client_secret = secret("DASHBOARD_DISCORD_CLIENT_SECRET")
        if client_secret and not review_url:
            raise ValueError("Discord sign-in needs DASHBOARD_PUBLIC_URL, the address Discord sends people back to")
        if review_url and not client_secret:
            raise ValueError("DASHBOARD_PUBLIC_URL is only used for Discord sign-in; "
                             "also set DASHBOARD_DISCORD_CLIENT_SECRET or DASHBOARD_DISCORD_CLIENT_SECRET_FILE")
        if client_secret and (not 16 <= len(client_secret) <= 512 or any(c.isspace() for c in client_secret)):
            raise ValueError("DASHBOARD_DISCORD_CLIENT_SECRET is not a Discord client secret")
        if client_secret and (dashboard_token or dashboard_token_file):
            raise ValueError("The access key is turned off when Discord sign-in is set up; "
                             "remove DASHBOARD_TOKEN and DASHBOARD_TOKEN_FILE")
        if client_secret and not token:
            raise ValueError("Discord sign-in checks server membership with the bot, so it needs BOT_TOKEN")
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
            dashboard_enabled=boolean("DASHBOARD_ENABLED"),
            dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=positive("DASHBOARD_PORT", 9101, maximum=65535),
            dashboard_token=dashboard_token, dashboard_token_file=dashboard_token_file,
            dashboard_public_url=review_url, dashboard_discord_client_secret=client_secret,
            dashboard_replay_limit=positive("DASHBOARD_REPLAY_LIMIT", 500, maximum=500),
            history_retention_days=positive("HISTORY_RETENTION_DAYS", 90, maximum=3650),
            history_max_rows=positive("HISTORY_MAX_ROWS", 50000, maximum=1000000),
        )
