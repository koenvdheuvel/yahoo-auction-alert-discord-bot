"""Validated configuration; environment loading belongs to the entry point."""
from dataclasses import dataclass, field
import os
import re
import stat
from urllib.parse import urlsplit

from dashboard_limits import parse_proxies
from marketplaces import MARKETPLACES


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


# An instance label: host:port, an IP address, or [IPv6]:port.
INSTANCE = re.compile(r"[A-Za-z0-9._:%@/\[\]-]{1,255}")


def prometheus_url(value):
    """The Prometheus that scrapes the bot, for the graphs on the dashboard's Status page."""
    value = value.strip()
    if not value:
        return ""
    parts = urlsplit(value)
    try:
        parts.port
    except ValueError:
        raise ValueError("PROMETHEUS_URL has an invalid port") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("PROMETHEUS_URL must start with http:// or https://, such as http://prometheus:9090")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("PROMETHEUS_URL must be the server's address, without a user name, password or query")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


# Settings that were renamed along with the dashboard. An old name stops startup, so a missed
# rename does not go unnoticed. A missed REVIEW_DISCORD_CLIENT_SECRET, for example, would
# otherwise turn Discord sign-in off and switch to the access key.
RENAMED = {f"REVIEW_{name}": f"DASHBOARD_{name}" for name in (
    "ENABLED", "HOST", "PORT", "TOKEN", "TOKEN_FILE", "PUBLIC_URL", "DISCORD_CLIENT_SECRET",
    "DISCORD_CLIENT_SECRET_FILE", "REPLAY_LIMIT")}


def refuse_renamed():
    """Raise when the environment still sets a renamed setting, even to an empty value."""
    old = sorted(name for name in RENAMED if name in os.environ)
    if old:
        raise ValueError("Rename these settings: " + ", ".join(f"{name} to {RENAMED[name]}" for name in old))


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
    enabled_sources: tuple = tuple(marketplace.source for marketplace in MARKETPLACES)
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
    # Reverse proxies (as ip_network objects) whose X-Forwarded-For and X-Forwarded-Proto count.
    dashboard_trusted_proxies: tuple = ()
    history_retention_days: int = 90
    history_max_rows: int = 50000
    # The Status page's graphs: the Prometheus that scrapes the bot, and the bot's instance label
    # there when more than one bot reports to it. Without the address there are no graphs.
    prometheus_url: str = ""
    prometheus_instance: str = ""

    @property
    def discord_sign_in(self):
        return bool(self.dashboard_discord_client_secret)

    @classmethod
    def from_env(cls, require_token=True):
        refuse_renamed()
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
        address = public_url(os.getenv("DASHBOARD_PUBLIC_URL", ""))
        client_secret = secret("DASHBOARD_DISCORD_CLIENT_SECRET")
        if client_secret and not address:
            raise ValueError("Discord sign-in needs DASHBOARD_PUBLIC_URL, the address Discord sends people back to")
        if address and not client_secret:
            raise ValueError("DASHBOARD_PUBLIC_URL is only used for Discord sign-in; "
                             "also set DASHBOARD_DISCORD_CLIENT_SECRET or DASHBOARD_DISCORD_CLIENT_SECRET_FILE")
        if client_secret and (not 16 <= len(client_secret) <= 512 or any(c.isspace() for c in client_secret)):
            raise ValueError("DASHBOARD_DISCORD_CLIENT_SECRET is not a Discord client secret")
        if client_secret and (dashboard_token or dashboard_token_file):
            raise ValueError("The access key is turned off when Discord sign-in is set up; "
                             "remove DASHBOARD_TOKEN and DASHBOARD_TOKEN_FILE")
        if client_secret and not token:
            raise ValueError("Discord sign-in checks server membership with the bot, so it needs BOT_TOKEN")
        prometheus = prometheus_url(os.getenv("PROMETHEUS_URL", ""))
        instance = os.getenv("PROMETHEUS_INSTANCE", "").strip()
        if instance and not INSTANCE.fullmatch(instance):
            raise ValueError("PROMETHEUS_INSTANCE must be an instance label, such as auction-bot:9100")
        if instance and not prometheus:
            raise ValueError("PROMETHEUS_INSTANCE is only used for the dashboard's graphs; also set PROMETHEUS_URL")
        sources = tuple(marketplace.source for marketplace in MARKETPLACES if boolean(marketplace.setting))
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
            dashboard_public_url=address, dashboard_discord_client_secret=client_secret,
            dashboard_replay_limit=positive("DASHBOARD_REPLAY_LIMIT", 500, maximum=500),
            dashboard_trusted_proxies=parse_proxies(os.getenv("DASHBOARD_TRUSTED_PROXIES", "")),
            history_retention_days=positive("HISTORY_RETENTION_DAYS", 90, maximum=3650),
            history_max_rows=positive("HISTORY_MAX_ROWS", 50000, maximum=1000000),
            prometheus_url=prometheus, prometheus_instance=instance,
        )
