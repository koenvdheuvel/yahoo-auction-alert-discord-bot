"""Authenticated operator UI, served independently of Discord and monitoring."""
import argparse
import asyncio
from collections import deque
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import time
from urllib.parse import urlsplit

from aiohttp import web

from review_repository import ReviewConflict, ReviewNotFound, ReviewValidation
from review_service import ReviewBusy, ReviewService, identifier


logger = logging.getLogger(__name__)
# The Vite build of frontend/. The container copies only this directory, not the sources.
ASSETS = Path(__file__).resolve().parent / "frontend" / "dist"
COOKIE = "filter_lab_session"
SESSION_SECONDS = 12 * 3600
SOURCES = {"yahooauction", "mercari", "surugaya"}
# Vite writes this placeholder into index.html (html.cspNonce); each page view gets a new value.
NONCE_PLACEHOLDER = "__CSP_NONCE__"
ASSET_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}")
ASSET_TYPES = {".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".woff": "font/woff",
               ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
ERROR_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
               413: "payload_too_large", 415: "unsupported_media_type", 429: "rate_limited"}


def content_security_policy(nonce=None):
    # MUI injects its styles at runtime in <style> elements, which the per-page nonce allows.
    styles = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
    return ("default-src 'self'; script-src 'self'; "
            f"style-src {styles}; img-src 'self' https: http:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def review_key(settings):
    """Persist a generated operator key privately; never put it in logs or URLs."""
    if settings.review_token:
        if not 16 <= len(settings.review_token) <= 512:
            raise ValueError("REVIEW_TOKEN must contain between 16 and 512 characters")
        return settings.review_token
    path = Path(settings.review_token_file or (settings.database_path + ".review-token"))
    if settings.database_path == ":memory:" and not settings.review_token_file:
        raise ValueError("In-memory review requires REVIEW_TOKEN or REVIEW_TOKEN_FILE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK)
        with os.fdopen(descriptor) as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ValueError("The review access-key file must be a private regular file (mode 600)")
            token = handle.read(4096).strip()
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(token + "\n")
        logger.info("review_key_created", extra={"fields": {"path": str(path)}})
    if len(token) < 16 or len(token) > 512:
        raise ValueError("The review access-key file is invalid")
    return token


def _whole_number(query, name, default, minimum, maximum):
    raw = query.get(name, "")
    if raw == "":
        return default
    if not raw.isascii() or not raw.isdigit() or not minimum <= int(raw) <= maximum:
        raise ReviewValidation(f"{name} must be a whole number from {minimum} to {maximum}")
    return int(raw)


def _choice(query, name, allowed, message):
    value = query.get(name, "")
    if value and value not in allowed:
        raise ReviewValidation(message)
    return value


def _flag(query, name):
    return _choice(query, name, {"0", "1", "true", "false"}, f"{name} must be true or false") in {"1", "true"}


class ReviewServer:
    def __init__(self, settings, repository, metrics=None, *, channel_names=None, bot_running=False, assets=ASSETS):
        """channel_names maps a set of channel IDs to display names; the bot passes its cache.
        bot_running says whether this process delivers to Discord, which is what removes queued posts."""
        self.settings, self.repository, self.metrics = settings, repository, metrics
        self.channel_names = channel_names
        self.bot_running = bot_running
        self.assets = Path(assets)
        self.service = ReviewService(repository, settings.review_replay_limit)
        self.runner = None
        self.site = None
        self.token = None
        self.sessions = {}
        self.login_failures = deque()
        self.started = False

    def session_seconds(self, request):
        """Seconds left in the request's session; 0 when it has none."""
        cookie = request.cookies.get(COOKIE, "")
        return max(0.0, self.sessions.get(cookie, 0) - time.monotonic()) if cookie else 0.0

    def authenticated(self, request):
        return self.session_seconds(request) > 0

    @staticmethod
    def same_origin(request):
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            return (parsed.scheme == request.scheme and parsed.netloc == request.host
                    and not parsed.path and not parsed.query and not parsed.fragment)
        return request.headers.get("Sec-Fetch-Site") in {"same-origin", "none"}

    def application(self, token):
        self.token = token

        @web.middleware
        async def guard(request, handler):
            started = time.monotonic()
            try:
                # Behind a TLS-terminating proxy (traefik) the browser's Origin is https while the
                # proxied request is http; adopt the forwarded scheme so the same-origin check and
                # the Secure cookie flag reflect what the browser sees. A cross-site page cannot set
                # this header without a CORS preflight, which is never granted.
                forwarded = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
                if forwarded in {"http", "https"} and forwarded != request.scheme:
                    request = request.clone(scheme=forwarded)
                if request.path.startswith("/api/"):
                    if request.method not in {"GET", "HEAD", "OPTIONS"} and not self.same_origin(request):
                        raise web.HTTPForbidden(reason="Changes must come from a Filter Lab page at this address")
                    if request.path not in {"/api/session", "/api/login"} and not self.authenticated(request):
                        raise web.HTTPUnauthorized(reason="Sign in with your access key")
                response = await handler(request)
            except ValueError as error:
                # ReviewValidation and RulesetError are ValueErrors; a ruleset error names its field.
                body = {"error": "invalid_request", "message": str(error)}
                if getattr(error, "path", ""):
                    body["field"] = error.path
                response = web.json_response(body, status=400)
            except ReviewConflict as error:
                response = web.json_response({"error": "version_conflict", "message": str(error)}, status=409)
            except ReviewNotFound as error:
                response = web.json_response({"error": "not_found", "message": str(error)}, status=404)
            except ReviewBusy as error:
                response = web.json_response({"error": "busy", "message": str(error)}, status=429,
                                             headers={"Retry-After": "2"})
            except web.HTTPException as error:
                response = web.json_response({"error": ERROR_CODES.get(error.status, "http_error"),
                                              "message": error.reason}, status=error.status)
                if error.status == 429:
                    response.headers["Retry-After"] = "60"
            except Exception:
                logger.exception("review_request_failed", extra={"fields": {
                    "operation": request.match_info.route.name or "unknown"}})
                response = web.json_response({"error": "internal_error",
                                             "message": "The request failed. See the application logs."}, status=500)
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Content-Security-Policy", content_security_policy())
            response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
            if self.metrics is not None and hasattr(self.metrics, "review_requests"):
                operation = request.match_info.route.name or "unknown"
                outcome = "success" if response.status < 400 else (
                    "server_error" if response.status >= 500 else "client_error")
                self.metrics.review_requests.labels(operation, outcome).inc()
                self.metrics.review_duration.labels(operation).observe(time.monotonic() - started)
            return response

        app = web.Application(middlewares=[guard], client_max_size=128 * 1024)
        app.add_routes([
            web.get("/", self.index, name="index"),
            web.get("/assets/{filename}", self.asset, name="asset"),
            web.get("/api/session", self.session, name="session"),
            web.post("/api/login", self.login, name="login"),
            web.delete("/api/session", self.logout, name="logout"),
            web.get("/api/alerts", self.alerts, name="alerts"),
            web.get("/api/alerts/{id}/rules", self.rules, name="rules"),
            web.get("/api/candidates", self.candidates, name="candidates"),
            web.post("/api/rules/validate", self.validate, name="rules_validate"),
            web.post("/api/preview", self.preview, name="preview"),
            web.post("/api/replay", self.replay, name="replay"),
            web.post("/api/alerts/{id}/publish", self.publish, name="publish"),
            web.post("/api/alerts/{id}/rollback", self.rollback, name="rollback"),
            web.post("/api/alerts/{id}/posts/removal-preview", self.post_removal_preview, name="post_removal_preview"),
            web.get("/api/alerts/{id}/posts/removal", self.post_removal_status, name="post_removal_status"),
            web.post("/api/alerts/{id}/posts/removal", self.post_removal, name="post_removal"),
            web.post("/api/history/import", self.import_history, name="history_import"),
        ])
        return app

    async def start(self):
        if self.started or not self.settings.review_enabled:
            return
        token = await asyncio.to_thread(review_key, self.settings)
        app = self.application(token)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=15)
        try:
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, self.settings.review_host, self.settings.review_port)
            await self.site.start()
        except Exception:
            await self.close()
            raise
        self.started = True
        logger.info("review_started", extra={"fields": {
            "host": self.settings.review_host, "port": self.settings.review_port}})

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
        await self.service.close()
        self.sessions.clear()
        self.started = False

    @staticmethod
    async def body(request):
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType(reason="Send JSON for this operation")
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ReviewValidation("The request must contain valid JSON") from None
        if not isinstance(data, dict):
            raise ReviewValidation("The request must contain a JSON object")
        return data

    async def index(self, request):
        try:
            page = await asyncio.to_thread((self.assets / "index.html").read_text, encoding="utf-8")
        except FileNotFoundError:
            return web.Response(status=503, text="Filter Lab's interface is not built. "
                                "Run `npm ci && npm run build` in frontend/, then reload.")
        nonce = secrets.token_urlsafe(18)
        response = web.Response(text=page.replace(NONCE_PLACEHOLDER, nonce), content_type="text/html")
        response.headers["Content-Security-Policy"] = content_security_policy(nonce)
        return response

    async def asset(self, request):
        name = request.match_info["filename"]
        path = self.assets / "assets" / name
        if not ASSET_NAME.fullmatch(name) or path.suffix not in ASSET_TYPES or not path.is_file():
            raise web.HTTPNotFound()
        # Build output names contain a content hash, so a cached copy never goes stale.
        return web.FileResponse(path, headers={"Content-Type": ASSET_TYPES[path.suffix],
                                               "Cache-Control": "public, max-age=31536000, immutable"})

    async def session(self, request):
        remaining = self.session_seconds(request)
        if not remaining:
            return web.json_response({"authenticated": False})
        return web.json_response({"authenticated": True, "expires_in": int(remaining),
                                  "replay_limit": self.settings.review_replay_limit})

    async def login(self, request):
        data = await self.body(request)
        # Check after reading the body so concurrent requests cannot all reserve
        # the same remaining attempt before yielding to the event loop.
        now = time.monotonic()
        while self.login_failures and self.login_failures[0] < now - 60:
            self.login_failures.popleft()
        if len(self.login_failures) >= 10:
            raise web.HTTPTooManyRequests(reason="Too many attempts. Try again in a minute.")
        supplied = data.get("token", "")
        if not isinstance(supplied, str) or len(supplied) > 512 or not secrets.compare_digest(
                supplied.encode(), self.token.encode()):
            self.login_failures.append(now)
            raise web.HTTPUnauthorized(reason="The access key is incorrect")
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
        if len(self.sessions) >= 128:
            oldest = min(self.sessions, key=self.sessions.get)
            del self.sessions[oldest]
        cookie = secrets.token_urlsafe(32)
        self.sessions[cookie] = now + SESSION_SECONDS
        response = web.json_response({"authenticated": True, "expires_in": SESSION_SECONDS,
                                      "replay_limit": self.settings.review_replay_limit})
        response.set_cookie(COOKIE, cookie, httponly=True, samesite="Strict", secure=request.secure,
                            max_age=SESSION_SECONDS, path="/")
        return response

    async def logout(self, request):
        self.sessions.pop(request.cookies.get(COOKIE, ""), None)
        response = web.json_response({"authenticated": False})
        response.del_cookie(COOKIE, path="/")
        return response

    async def alerts(self, request):
        result = await self.repository.review_alerts()
        names = {}
        if self.channel_names is not None:
            try:
                names = self.channel_names({alert["channel_id"] for alert in result["alerts"]})
            except Exception:
                # Names are a convenience; the list still works with channel IDs.
                logger.exception("review_channel_names_failed")
        for alert in result["alerts"]:
            alert["channel_name"] = names.get(alert["channel_id"])
        return web.json_response(result)

    async def rules(self, request):
        return web.json_response(await self.service.rules(request.match_info["id"]))

    async def candidates(self, request):
        query = request.query
        alert_id = identifier(query["alert_id"], "alert_id") if query.get("alert_id") else None
        search = query.get("search", "")
        if len(search) > 256:
            raise ReviewValidation("Search must contain at most 256 characters")
        result = await self.repository.list_candidates(
            alert_id=alert_id, search=search,
            source=_choice(query, "source", SOURCES, "Unknown source"),
            verdict=_choice(query, "verdict", {"accepted", "filtered", "review"}, "Unknown decision"),
            limit=_whole_number(query, "limit", 50, 1, 100),
            offset=_whole_number(query, "offset", 0, 0, 10 ** 7),
            cursor=query.get("cursor") or None, latest=_flag(query, "latest"), facets=_flag(query, "facets"))
        return web.json_response(result)

    async def validate(self, request):
        return web.json_response(self.service.validate(await self.body(request)))

    async def preview(self, request):
        return web.json_response(await self.service.preview(await self.body(request)))

    async def replay(self, request):
        return web.json_response(await self.service.replay(await self.body(request)))

    async def publish(self, request):
        return web.json_response(await self.service.publish(
            request.match_info["id"], await self.body(request)))

    async def rollback(self, request):
        return web.json_response(await self.service.rollback(
            request.match_info["id"], await self.body(request)))

    async def import_history(self, request):
        await self.body(request)
        return web.json_response(await self.repository.bootstrap_history())

    async def post_removal_preview(self, request):
        result = await self.service.post_removal_preview(request.match_info["id"], await self.body(request))
        return web.json_response({**result, "bot_running": self.bot_running})

    async def post_removal(self, request):
        result = await self.service.remove_posts(request.match_info["id"], await self.body(request))
        return web.json_response({**result, "bot_running": self.bot_running})

    async def post_removal_status(self, request):
        result = await self.repository.post_removal_status(identifier(request.match_info["id"], "alert_id"))
        return web.json_response({**result, "bot_running": self.bot_running})


def main(argv=None):
    from config import Settings
    from models import configure_database, create_tables
    from observability import Metrics, configure_logging
    from repositories import Repository

    import dotenv

    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(description="Run Filter Lab without connecting the Discord bot")
    parser.add_argument("--database", help="SQLite database filename")
    parser.add_argument("--host", help="Listener host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Listener port (default 9101)")
    parser.add_argument("--init", action="store_true", help="Create a new empty database explicitly")
    args = parser.parse_args(argv)
    settings = Settings.from_env(require_token=False)
    settings = replace(settings, review_enabled=True,
                       database_path=args.database or settings.database_path,
                       review_host=args.host or settings.review_host,
                       review_port=settings.review_port if args.port is None else args.port)
    if not 1 <= settings.review_port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if not args.init and not Path(settings.database_path).is_file():
        parser.error("Database does not exist. Start the bot once or use --init for an empty archive.")
    configure_logging(settings.log_level, secrets=(settings.token, settings.review_token))
    configure_database(settings.database_path)
    create_tables()
    repository = Repository(Metrics())
    server = ReviewServer(settings, repository, repository.metrics)
    token = review_key(settings)
    app = server.application(token)

    async def startup(_):
        await repository.start()

    async def cleanup(_):
        try:
            await server.close()
        finally:
            await repository.close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    web.run_app(app, host=settings.review_host, port=settings.review_port, access_log=None)


if __name__ == "__main__":
    main()
