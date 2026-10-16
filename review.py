"""Authenticated operator UI, served independently of Discord and monitoring."""
import argparse
import asyncio
import base64
import binascii
from collections import deque
from dataclasses import dataclass, replace
from functools import partial
import hashlib
import hmac
import html
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import time
from urllib.parse import urlencode, urlsplit

from aiohttp import web

from review_auth import (CALLBACK_PATH, LOGIN_PATH, DiscordGuilds, DiscordOAuth, DiscordRefused,
                         DiscordUnavailable)
from review_repository import ReviewConflict, ReviewNotFound, ReviewValidation
from review_service import ReviewBusy, ReviewService, identifier


logger = logging.getLogger(__name__)
# The Vite build of frontend/. The container copies only this directory, not the sources.
ASSETS = Path(__file__).resolve().parent / "frontend" / "dist"
COOKIE = "filter_lab_session"
SESSION_SECONDS = 12 * 3600
MAX_SESSIONS = 128
# Sessions one Discord user may hold, so nobody can push everyone else's sessions out.
MAX_SESSIONS_PER_USER = 5
# Discord sign-in. This cookie ties Discord's answer to the browser that started the sign-in.
LOGIN_COOKIE = "filter_lab_login"
LOGIN_SECONDS = 600
FINISH_PATH = LOGIN_PATH + "/finish"
# How long one check of a person's Discord servers counts for. After Discord fails to answer,
# requests are refused for this long before Discord is asked again.
ACCESS_SECONDS = 300
ACCESS_RETRY_SECONDS = 30
# A session ended by a check is remembered this long, so a reload can still say why.
REVOKED_SECONDS = 600
# Failed sign-ins allowed per minute, for the access key and Discord together.
LOGIN_FAILURES_PER_MINUTE = 10
# Where sign-in may return to: the UI's page with its search and tab, nothing else.
NEXT_PAGE = re.compile(r"/(\?[A-Za-z0-9=&_-]{1,200})?")
SOURCES = {"yahooauction", "mercari", "surugaya"}
FEEDBACK = {"relevant", "wrong_product", "accessory", "bundle", "unsure"}
# Vite writes this placeholder into index.html (html.cspNonce); each page view gets a new value.
NONCE_PLACEHOLDER = "__CSP_NONCE__"
ASSET_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}")
ASSET_TYPES = {".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".woff": "font/woff",
               ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
ERROR_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
               413: "payload_too_large", 415: "unsupported_media_type", 429: "rate_limited"}
# Discord sends the browser back from discord.com, another site, so the browser leaves out the
# SameSite=Strict session cookie on that request and on redirects that follow it. This page
# moves on from Filter Lab itself, which makes the next request same-site, so the cookie is sent.
HOP_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Signing in to Filter Lab</title>
<meta http-equiv="refresh" content="0; url={target}"></head>
<body><p>Signing in to Filter Lab. <a href="{target}">Continue</a></p></body></html>
"""


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


def _label(data):
    label = data.get("label")
    if label is not None and (not isinstance(label, str) or label not in FEEDBACK):
        raise ReviewValidation("Select a valid relevance label")
    return label


def _next_page(value):
    return value if isinstance(value, str) and NEXT_PAGE.fullmatch(value) else "/"


def _redirect(location, status=302):
    return web.Response(status=status, headers={"Location": location})


def _origin(scheme, host):
    """scheme://host as REVIEW_PUBLIC_URL writes it: lowercase, without the default port."""
    host = host.lower()
    default = {"https": ":443", "http": ":80"}.get(scheme, "")
    if default and host.endswith(default):
        host = host[:-len(default)]
    return f"{scheme}://{host}"


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@dataclass(eq=False)
class Session:
    expires: float
    # The Discord user: id, name, username and avatar_url. None when signed in with the access key.
    user: dict | None = None
    # Server ID to name and icon for the servers this person may see. None means every server.
    guilds: dict | None = None
    checked: float = 0.0
    failed: float = float("-inf")
    check: asyncio.Task | None = None


# The request's session, set by the guard on every /api/ route that needs one.
SESSION = web.RequestKey("session", Session)


class AccessRevoked(Exception):
    """The person no longer manages any of the bot's servers, so their session has ended."""


class AccessUnknown(Exception):
    """Discord did not answer, so the person's access cannot be confirmed."""


class ReviewServer:
    def __init__(self, settings, repository, metrics=None, *, channel_names=None, bot_running=False, assets=ASSETS,
                 guild_access=None, oauth=None, access_seconds=ACCESS_SECONDS):
        """channel_names maps a set of channel IDs to display names; the bot passes its cache.
        bot_running says whether this process delivers to Discord, which is what removes queued posts.

        With Discord sign-in, guild_access checks people's servers with the bot's token and
        oauth runs the sign-in. Tests and the fake Discord harness pass their own oauth.
        """
        self.settings, self.repository, self.metrics = settings, repository, metrics
        self.channel_names = channel_names
        self.bot_running = bot_running
        self.assets = Path(assets)
        self.service = ReviewService(repository, settings.review_replay_limit)
        self.discord = settings.discord_sign_in
        if self.discord and guild_access is None:
            raise ValueError("Discord sign-in needs the bot's Discord client to check server access")
        self.public_url = settings.review_public_url
        self.guild_access = guild_access
        self.oauth = oauth or (DiscordOAuth.from_settings(settings) if self.discord else None)
        self.access_seconds = access_seconds
        self.runner = None
        self.site = None
        self.token = None
        self.sessions = {}
        # Signs sign-in attempts, so the server does not keep them. A restart forgets attempts in progress.
        self.login_key = secrets.token_bytes(32)
        self.login_seconds = LOGIN_SECONDS
        # Cookies of sessions a check ended, to the time they are forgotten.
        self.revoked = {}
        self.login_failures = deque()
        self.started = False

    @property
    def method(self):
        return "discord" if self.discord else "access_key"

    def current_session(self, request):
        """The request's session and its cookie, or (None, cookie) when it has none or it expired."""
        cookie = request.cookies.get(COOKIE, "")
        session = self.sessions.get(cookie) if cookie else None
        if session is not None and session.expires <= time.monotonic():
            session = None
        return session, cookie

    async def require_session(self, request):
        session, cookie = self.current_session(request)
        if session is None and self.revoked.get(cookie, 0) > time.monotonic():
            raise AccessRevoked()
        if session is None:
            raise web.HTTPUnauthorized(reason="Sign in with Discord" if self.discord
                                       else "Sign in with your access key")
        if session.user is not None:
            await self.confirm_access(cookie, session)
        return session

    async def confirm_access(self, cookie, session):
        """Check the person's Discord servers again once the last check is too old.

        Requests that arrive while a check runs wait for it instead of starting their own.
        """
        if time.monotonic() - session.checked >= self.access_seconds:
            if session.check is None:
                if time.monotonic() - session.failed < ACCESS_RETRY_SECONDS:
                    raise AccessUnknown()
                session.check = asyncio.create_task(self._recheck(cookie, session))
                # Every waiter gets the error; this keeps asyncio quiet when all of them went away.
                session.check.add_done_callback(lambda task: task.cancelled() or task.exception())
            try:
                await asyncio.shield(session.check)
            except DiscordUnavailable:
                raise AccessUnknown() from None
        if not session.guilds:
            raise AccessRevoked()

    async def _recheck(self, cookie, session):
        user_id = session.user["id"]
        try:
            access = await self.guild_access.check(int(user_id))
        except Exception as error:
            # Fail closed: until a check succeeds, the session gets nothing.
            session.failed = time.monotonic()
            self.count("review_access_checks", "error")
            logger.warning("review_access_check_failed", extra={"fields": {
                "actor_id": user_id, "error": str(error)[:300]}})
            raise
        finally:
            session.check = None
        lost = sorted(set(session.guilds) - set(access.guilds))
        session.guilds, session.checked = access.guilds, time.monotonic()
        if not access.guilds:
            self.sessions.pop(cookie, None)
            now = time.monotonic()
            self.revoked = {key: until for key, until in self.revoked.items() if until > now}
            if len(self.revoked) >= MAX_SESSIONS:
                del self.revoked[min(self.revoked, key=self.revoked.get)]
            self.revoked[cookie] = now + REVOKED_SECONDS
        outcome = "revoked" if not access.guilds else "reduced" if lost else "kept"
        self.count("review_access_checks", outcome)
        if lost:
            logger.warning("review_access_revoked", extra={"fields": {
                "actor_id": user_id, "guild_ids": [str(guild) for guild in lost],
                "remaining_guilds": len(access.guilds), "session_ended": not access.guilds}})

    def count(self, name, *labels):
        metric = getattr(self.metrics, name, None) if self.metrics is not None else None
        if metric is not None:
            metric.labels(*labels).inc()

    def _sign(self, *parts):
        return _b64(hmac.new(self.login_key, "|".join(parts).encode(), hashlib.sha256).digest())

    def new_login(self, page):
        """A Discord sign-in attempt, as (login cookie, state, PKCE verifier).

        The server keeps nothing, so starting many sign-ins cannot push out anyone else's. The
        cookie holds a random value and the page to return to. The state holds when the attempt
        started and a signature over that time and the cookie, so only the browser with the
        cookie can finish it, within LOGIN_SECONDS. The verifier is a signature of the state.
        """
        cookie = f"{secrets.token_urlsafe(24)}.{_b64(page.encode())}"
        issued = str(int(time.time()))
        state = f"{issued}.{self._sign('state', issued, cookie)}"
        return cookie, state, self._sign("pkce", state)

    def check_login(self, state, cookie):
        """(problem, page to return to, PKCE verifier); problem is None when the state is good."""
        issued, _, signature = state.partition(".")
        if not issued.isdigit() or len(state) > 128:
            return "invalid", None, None
        if not cookie:
            return "other_browser", None, None
        if not hmac.compare_digest(signature.encode(), self._sign("state", issued, cookie).encode()):
            # A forged state, or the cookie of a later sign-in started in another tab.
            return "mismatch", None, None
        if time.time() - int(issued) > self.login_seconds:
            return "expired", None, None
        try:
            encoded = cookie.partition(".")[2]
            page = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        except (binascii.Error, UnicodeDecodeError):
            page = "/"
        return None, _next_page(page), self._sign("pkce", state)

    def login_blocked(self):
        now = time.monotonic()
        while self.login_failures and self.login_failures[0] < now - 60:
            self.login_failures.popleft()
        return len(self.login_failures) >= LOGIN_FAILURES_PER_MINUTE

    def open_session(self, session):
        now = time.monotonic()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}
        if session.user is not None:
            own = [key for key, value in self.sessions.items()
                   if value.user is not None and value.user["id"] == session.user["id"]]
            if len(own) >= MAX_SESSIONS_PER_USER:
                del self.sessions[min(own, key=lambda key: self.sessions[key].expires)]
        if len(self.sessions) >= MAX_SESSIONS:
            del self.sessions[min(self.sessions, key=lambda key: self.sessions[key].expires)]
        cookie = secrets.token_urlsafe(32)
        self.sessions[cookie] = session
        return cookie

    @staticmethod
    def set_session_cookie(response, request, cookie):
        response.set_cookie(COOKIE, cookie, httponly=True, samesite="Strict", secure=request.secure,
                            max_age=SESSION_SECONDS, path="/")

    @staticmethod
    def guilds(request):
        """The server IDs this request may see, or None for every server (the access key)."""
        session = request[SESSION]
        return None if session.guilds is None else frozenset(session.guilds)

    @staticmethod
    def actor(request):
        """Who made a change, for the logs. Changes made with the access key have no Discord user."""
        user = request[SESSION].user
        return {"actor_id": user["id"] if user else None, "sign_in": "discord" if user else "access_key"}

    @staticmethod
    def same_origin(request):
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            return (parsed.scheme == request.scheme and parsed.netloc == request.host
                    and not parsed.path and not parsed.query and not parsed.fragment)
        return request.headers.get("Sec-Fetch-Site") in {"same-origin", "none"}

    def application(self, token=None):
        """The aiohttp application. token is the access key; Discord sign-in does not use one."""
        if not self.discord and not token:
            raise ValueError("Access-key sign-in needs the access key")
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
                    if request.path not in {"/api/session", "/api/login"}:
                        request[SESSION] = await self.require_session(request)
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
            except AccessRevoked:
                response = web.json_response({"error": "access_revoked", "message": (
                    "You no longer have Manage Channels in a server this bot is in, so you were signed out.")},
                    status=401)
            except AccessUnknown:
                response = web.json_response({"error": "access_unknown", "message": (
                    "Filter Lab can't reach Discord to confirm your access. Try again in a minute.")},
                    status=503, headers={"Retry-After": str(ACCESS_RETRY_SECONDS)})
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
            web.delete("/api/session", self.logout, name="logout"),
            web.get("/api/alerts", self.alerts, name="alerts"),
            web.get("/api/alerts/{id}/rules", self.rules, name="rules"),
            web.get("/api/candidates", self.candidates, name="candidates"),
            web.post("/api/candidates/feedback", self.feedback_many, name="feedback_bulk"),
            web.post("/api/candidates/{id}/feedback", self.feedback, name="feedback"),
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
        if self.discord:
            # Discord sign-in is then the only way in; the access-key route does not exist.
            app.add_routes([
                web.get(LOGIN_PATH, self.discord_start, name="discord_start"),
                web.get(CALLBACK_PATH, self.discord_callback, name="discord_callback"),
                web.get(FINISH_PATH, self.discord_finish, name="discord_finish"),
            ])
        else:
            app.add_routes([web.post("/api/login", self.login, name="login")])
        return app

    async def start(self):
        if self.started or not self.settings.review_enabled:
            return
        token = None if self.discord else await asyncio.to_thread(review_key, self.settings)
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
            "host": self.settings.review_host, "port": self.settings.review_port, "sign_in": self.method}})

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
        await self.service.close()
        if self.oauth is not None:
            await self.oauth.close()
        checks = [session.check for session in self.sessions.values() if session.check is not None]
        for check in checks:
            check.cancel()
        await asyncio.gather(*checks, return_exceptions=True)
        self.sessions.clear()
        self.revoked.clear()
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
        session, cookie = self.current_session(request)
        if session is not None and session.user is not None:
            try:
                await self.confirm_access(cookie, session)
            except AccessRevoked:
                return web.json_response({"authenticated": False, "method": self.method, "reason": "access_revoked"})
        if session is None and self.revoked.get(cookie, 0) > time.monotonic():
            return web.json_response({"authenticated": False, "method": self.method, "reason": "access_revoked"})
        if session is None:
            return web.json_response({"authenticated": False, "method": self.method})
        guilds = None if session.guilds is None else sorted(
            session.guilds.values(), key=lambda guild: (guild["name"].casefold(), guild["id"]))
        return web.json_response({"authenticated": True, "method": self.method,
                                  "expires_in": int(session.expires - time.monotonic()),
                                  "replay_limit": self.settings.review_replay_limit,
                                  "user": session.user, "guilds": guilds})

    async def login(self, request):
        """Access-key sign-in, only when Discord sign-in is not set up."""
        data = await self.body(request)
        # Check after reading the body so concurrent requests cannot all reserve
        # the same remaining attempt before yielding to the event loop.
        if self.login_blocked():
            self.count("review_logins", "access_key", "rate_limited")
            raise web.HTTPTooManyRequests(reason="Too many attempts. Try again in a minute.")
        supplied = data.get("token", "")
        if not isinstance(supplied, str) or len(supplied) > 512 or not secrets.compare_digest(
                supplied.encode(), self.token.encode()):
            self.login_failures.append(time.monotonic())
            self.count("review_logins", "access_key", "wrong_key")
            logger.warning("review_login_denied", extra={"fields": {"method": "access_key", "reason": "wrong_key"}})
            raise web.HTTPUnauthorized(reason="The access key is incorrect")
        cookie = self.open_session(Session(time.monotonic() + SESSION_SECONDS))
        self.count("review_logins", "access_key", "success")
        logger.info("review_login_succeeded", extra={"fields": {"method": "access_key"}})
        response = web.json_response({"authenticated": True, "method": self.method,
                                      "expires_in": SESSION_SECONDS,
                                      "replay_limit": self.settings.review_replay_limit,
                                      "user": None, "guilds": None})
        self.set_session_cookie(response, request, cookie)
        return response

    def signin_failed(self, reason, *, user=None, detail=None, counted=True, used_login=False):
        """Send the browser back to the sign-in page, which explains the reason.

        used_login: the request used up the sign-in attempt, so its login cookie goes too.
        """
        if counted:
            self.login_failures.append(time.monotonic())
        self.count("review_logins", "discord", reason)
        # Refusals while blocked are not logged one by one; the metric still counts them.
        log = logger.debug if reason == "rate_limited" else logger.warning
        log("review_login_denied", extra={"fields": {
            "method": "discord", "reason": reason, "detail": detail, "actor_id": user["id"] if user else None}})
        response = _redirect("/?" + urlencode({"signin": reason}), status=303)
        if used_login:
            response.del_cookie(LOGIN_COOKIE, path=LOGIN_PATH)
        return response

    async def discord_start(self, request):
        page = _next_page(request.query.get("next"))
        here = _origin(request.scheme, request.host)
        if here != self.public_url:
            if urlsplit(here).netloc == urlsplit(self.public_url).netloc:
                # Same host, other scheme: sending the browser on would come back here forever.
                logger.error("review_public_url_mismatch", extra={"fields": {
                    "request_scheme": request.scheme, "public_url": self.public_url}})
                return web.Response(status=500, text=(
                    f"Filter Lab was reached over {request.scheme}, but REVIEW_PUBLIC_URL is "
                    f"{self.public_url}. A reverse proxy that ends TLS must send X-Forwarded-Proto: https."))
            # The login cookie has to be set on the address Discord sends people back to.
            return _redirect(f"{self.public_url}{LOGIN_PATH}?{urlencode({'next': page})}")
        if self.login_blocked():
            return self.signin_failed("rate_limited", counted=False)
        try:
            client_id = await self.guild_access.application_id()
        except DiscordUnavailable as error:
            return self.signin_failed("discord_unavailable", detail=str(error)[:300], counted=False)
        cookie, state, verifier = self.new_login(page)
        response = _redirect(self.oauth.authorize_url(client_id, state, verifier))
        # Lax, so the browser sends it when Discord sends the person back; Strict would not be sent.
        response.set_cookie(LOGIN_COOKIE, cookie, httponly=True, samesite="Lax", secure=request.secure,
                            max_age=self.login_seconds, path=LOGIN_PATH)
        return response

    async def discord_callback(self, request):
        if self.login_blocked():
            return self.signin_failed("rate_limited", counted=False)
        query = request.query
        problem, page, verifier = self.check_login(query.get("state", ""), request.cookies.get(LOGIN_COOKIE, ""))
        if problem is not None:
            # Not counted for the rate limit: anyone can send a broken link, and counting those
            # would let them block every sign-in. Nothing here reaches Discord.
            return self.signin_failed("state", detail=problem, used_login=problem == "expired", counted=False)
        # From here the attempt is used up: the login cookie goes, so the same callback cannot run
        # twice in this browser, and Discord accepts each code only once anyway.
        failed = partial(self.signin_failed, used_login=True)
        if "error" in query:
            error = query["error"] if query["error"].isidentifier() else "other"
            return failed("cancelled" if error == "access_denied" else "discord_error", detail=error[:64])
        code = query.get("code", "")
        if not 1 <= len(code) <= 512:
            return failed("discord_error", detail="no_code")
        try:
            user = await self.oauth.identify(await self.guild_access.application_id(), code, verifier)
        except DiscordRefused as error:
            return failed("discord_error", detail=str(error))
        except DiscordUnavailable as error:
            return failed("discord_unavailable", detail=str(error)[:300])
        try:
            access = await self.guild_access.check(int(user["id"]))
        except DiscordUnavailable as error:
            return failed("discord_unavailable", user=user, detail=str(error)[:300])
        if not access.guilds:
            return failed("missing_permission" if access.member_of else "not_member", user=user)
        cookie = self.open_session(Session(time.monotonic() + SESSION_SECONDS, user=user,
                                           guilds=access.guilds, checked=time.monotonic()))
        self.count("review_logins", "discord", "success")
        logger.info("review_login_succeeded", extra={"fields": {
            "method": "discord", "actor_id": user["id"], "guild_ids": [str(guild) for guild in access.guilds]}})
        target = html.escape(f"{FINISH_PATH}?{urlencode({'next': page})}", quote=True)
        response = web.Response(text=HOP_PAGE.format(target=target), content_type="text/html")
        self.set_session_cookie(response, request, cookie)
        response.del_cookie(LOGIN_COOKIE, path=LOGIN_PATH)
        return response

    async def discord_finish(self, request):
        """The first same-site request after sign-in. It proves the session cookie arrives."""
        session, _ = self.current_session(request)
        if session is None:
            return self.signin_failed("cookie", counted=False)
        return _redirect(_next_page(request.query.get("next")), status=303)

    async def logout(self, request):
        self.revoked.pop(request.cookies.get(COOKIE, ""), None)
        session = self.sessions.pop(request.cookies.get(COOKIE, ""), None)
        if session is not None:
            logger.info("review_logout", extra={"fields": {
                "actor_id": session.user["id"] if session.user else None}})
        response = web.json_response({"authenticated": False, "method": self.method})
        response.del_cookie(COOKIE, path="/")
        return response

    async def alerts(self, request):
        result = await self.repository.review_alerts(guilds=self.guilds(request))
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
        return web.json_response(await self.service.rules(request.match_info["id"], self.guilds(request)))

    async def candidates(self, request):
        query = request.query
        alert_id = identifier(query["alert_id"], "alert_id") if query.get("alert_id") else None
        guild_id = identifier(query["guild_id"], "guild_id") if query.get("guild_id") else None
        search = query.get("search", "")
        if len(search) > 256:
            raise ReviewValidation("Search must contain at most 256 characters")
        result = await self.repository.list_candidates(
            alert_id=alert_id, search=search,
            source=_choice(query, "source", SOURCES, "Unknown source"),
            verdict=_choice(query, "verdict", {"accepted", "filtered", "review"}, "Unknown decision"),
            feedback=_choice(query, "feedback", FEEDBACK | {"unlabeled"}, "Unknown feedback label"),
            limit=_whole_number(query, "limit", 50, 1, 100),
            offset=_whole_number(query, "offset", 0, 0, 10 ** 7),
            cursor=query.get("cursor") or None, latest=_flag(query, "latest"), facets=_flag(query, "facets"),
            guilds=self.guilds(request), guild_id=guild_id)
        return web.json_response(result)

    async def validate(self, request):
        return web.json_response(self.service.validate(await self.body(request)))

    async def preview(self, request):
        return web.json_response(await self.service.preview(await self.body(request), self.guilds(request)))

    async def replay(self, request):
        return web.json_response(await self.service.replay(await self.body(request), self.guilds(request)))

    def log_labels(self, request, items, label):
        logger.info("review_labels_changed", extra={"fields": {
            **self.actor(request), "label": label, "count": len(items),
            "alert_ids": sorted({item["alert_id"] for item in items if item["alert_id"]}),
            "guild_ids": sorted({item["guild_id"] for item in items if item["guild_id"]})}})

    async def feedback(self, request):
        label = _label(await self.body(request))
        item = await self.repository.set_candidate_feedback(
            identifier(request.match_info["id"]), label, guilds=self.guilds(request))
        self.log_labels(request, [item], label)
        return web.json_response(item)

    async def feedback_many(self, request):
        data = await self.body(request)
        result = await self.repository.set_candidates_feedback(data.get("ids"), _label(data),
                                                               guilds=self.guilds(request))
        self.log_labels(request, result["items"], data.get("label"))
        return web.json_response(result)

    async def publish(self, request):
        version = await self.service.publish(request.match_info["id"], await self.body(request),
                                             self.guilds(request))
        logger.info("review_rules_published", extra={"fields": {
            **self.actor(request), "alert_id": version["alert_id"], "guild_id": version["guild_id"],
            "version_id": version["id"], "version": version["version"]}})
        return web.json_response(version)

    async def rollback(self, request):
        version = await self.service.rollback(request.match_info["id"], await self.body(request),
                                              self.guilds(request))
        logger.info("review_rules_restored", extra={"fields": {
            **self.actor(request), "alert_id": version["alert_id"], "guild_id": version["guild_id"],
            "version_id": version["id"], "version": version["version"],
            "restored_from_version_id": version["restored_from_version_id"]}})
        return web.json_response(version)

    async def import_history(self, request):
        await self.body(request)
        result = await self.repository.bootstrap_history(guilds=self.guilds(request))
        logger.info("review_history_imported", extra={"fields": {
            **self.actor(request), "imported": result["imported"], "skipped": result["skipped"]}})
        return web.json_response(result)

    async def post_removal_preview(self, request):
        result = await self.service.post_removal_preview(request.match_info["id"], await self.body(request),
                                                         self.guilds(request))
        return web.json_response({**result, "bot_running": self.bot_running})

    async def post_removal(self, request):
        data = await self.body(request)
        result = await self.service.remove_posts(request.match_info["id"], data, self.guilds(request))
        guild_id = result.pop("guild_id")
        logger.info("review_post_removal_queued", extra={"fields": {
            **self.actor(request), "alert_id": request.match_info["id"], "guild_id": guild_id,
            "version_id": str(data.get("version_id")), "queued": result["queued"], "skipped": result["skipped"]}})
        return web.json_response({**result, "bot_running": self.bot_running})

    async def post_removal_status(self, request):
        result = await self.repository.post_removal_status(identifier(request.match_info["id"], "alert_id"),
                                                           guilds=self.guilds(request))
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
    configure_logging(settings.log_level, secrets=(
        settings.token, settings.review_token, settings.review_discord_client_secret))
    configure_database(settings.database_path)
    create_tables()
    repository = Repository(Metrics())
    # Without the gateway there is no cache; Discord sign-in asks Discord's REST API with the bot token.
    guild_access = DiscordGuilds() if settings.discord_sign_in else None
    rest_app = None
    server = ReviewServer(settings, repository, repository.metrics, guild_access=guild_access)
    app = server.application(None if settings.discord_sign_in else review_key(settings))

    async def startup(_):
        nonlocal rest_app
        await repository.start()
        if guild_access is not None:
            import hikari

            rest_app = hikari.RESTApp()
            await rest_app.start()
            guild_access.rest = rest_app.acquire(settings.token, hikari.TokenType.BOT)
            guild_access.rest.start()

    async def cleanup(_):
        try:
            await server.close()
        finally:
            try:
                if rest_app is not None:
                    await guild_access.rest.close()
                    await rest_app.close()
            finally:
                await repository.close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    web.run_app(app, host=settings.review_host, port=settings.review_port, access_log=None)


if __name__ == "__main__":
    main()
