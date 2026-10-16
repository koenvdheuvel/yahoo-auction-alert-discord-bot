"""A small local stand-in for Discord, for tests and for trying Filter Lab's Discord sign-in.

It serves what Filter Lab asks Discord for: the authorize page, the token exchange and
/users/@me with the person's token, and the bot's calls for its servers, roles and members.
It is never used in production; Filter Lab only talks to it when a test or the harness in
devtools/filter_lab_harness.py passes its URLs in code.
"""
import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
import html
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit

from aiohttp import web

APPLICATION_ID = 900000000000000001
BOT_ID = APPLICATION_ID
PERMISSIONS = {"administrator": 1 << 3, "manage_channels": 1 << 4, "view_channel": 1 << 10,
               "send_messages": 1 << 11}


@dataclass
class FakeGuild:
    id: int
    name: str
    owner_id: int
    # Role ID to its permission bits. The @everyone role has the server's ID.
    roles: dict = field(default_factory=dict)
    # User ID to the role IDs the member has, without @everyone, as Discord sends them.
    members: dict = field(default_factory=dict)
    # User ID to an ISO 8601 time until which the member is in timeout.
    timeouts: dict = field(default_factory=dict)


def _not_found(code, message):
    return web.json_response({"code": code, "message": message}, status=404)


class FakeDiscord:
    def __init__(self, *, client_secret, bot_token, host="localhost", port=0):
        self.client_secret, self.bot_token = client_secret, bot_token
        self.host, self.port = host, port
        self.users = {}
        self.guilds = {}
        # (method, path) of every request, so tests can count calls.
        self.calls = []
        # When True, every API call answers 503, as if Discord were down.
        self.down = False
        # Seconds every API call waits before answering, as if Discord were slow.
        self.delay = 0
        self.codes = {}
        self.tokens = {}
        self.runner = None

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    @property
    def authorize_url(self):
        return self.base_url + "/oauth2/authorize"

    @property
    def api_url(self):
        return self.base_url + "/api/v10"

    def add_user(self, user_id, username, global_name=None, avatar=None):
        self.users[user_id] = {"id": str(user_id), "username": username, "global_name": global_name,
                               "avatar": avatar, "discriminator": "0", "public_flags": 0}

    def add_guild(self, guild_id, name, owner_id, everyone=PERMISSIONS["view_channel"]):
        guild = FakeGuild(guild_id, name, owner_id, roles={guild_id: everyone})
        self.guilds[guild_id] = guild
        return guild

    async def start(self):
        app = web.Application()
        app.add_routes([
            web.get("/oauth2/authorize", self.authorize_page),
            web.post("/oauth2/authorize", self.authorize_decision),
            web.post("/api/v10/oauth2/token", self.token),
            web.get("/api/v10/users/@me", self.me),
            web.get("/api/v10/users/@me/guilds", self.my_guilds),
            web.get("/api/v10/guilds/{guild}", self.guild),
            web.get("/api/v10/guilds/{guild}/members/{user}", self.member),
            web.get("/api/v10/oauth2/applications/@me", self.application),
            web.get("/embed/avatars/{name}", self.avatar),
            web.get("/fake", self.control_page),
            web.post("/fake", self.control),
        ])

        @web.middleware
        async def record(request, handler):
            self.calls.append((request.method, request.path))
            if request.path.startswith("/api/"):
                await asyncio.sleep(self.delay)
                if self.down:
                    return web.json_response({"message": "Service unavailable", "code": 0}, status=503)
            return await handler(request)

        app.middlewares.append(record)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, self.host, self.port).start()
        self.port = self.runner.addresses[0][1]

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    # OAuth2, as seen by the person's browser and by Filter Lab with the person's token.

    def _check_authorize(self, params):
        expected = {"response_type": "code", "client_id": str(APPLICATION_ID), "scope": "identify",
                    "code_challenge_method": "S256"}
        for name, value in expected.items():
            if params.get(name) != value:
                raise web.HTTPBadRequest(text=f"Invalid {name}")
        for name in ("redirect_uri", "state", "code_challenge"):
            if not params.get(name):
                raise web.HTTPBadRequest(text=f"Missing {name}")

    def issue_code(self, params, user_id):
        code = secrets.token_urlsafe(24)
        self.codes[code] = {"user_id": user_id, "redirect_uri": params["redirect_uri"],
                            "challenge": params["code_challenge"]}
        return code

    @staticmethod
    def _back(params, **answer):
        return params["redirect_uri"] + "?" + urlencode({**answer, "state": params["state"]})

    def approve(self, location, user_id):
        """The callback URL Discord would send the browser to after the person approves."""
        params = dict(parse_qsl(urlsplit(location).query))
        self._check_authorize(params)
        return self._back(params, code=self.issue_code(params, user_id))

    def cancel(self, location):
        """The callback URL Discord would send the browser to after the person cancels."""
        params = dict(parse_qsl(urlsplit(location).query))
        return self._back(params, error="access_denied",
                          error_description="The resource owner or authorization server denied the request")

    async def authorize_page(self, request):
        params = dict(request.query)
        self._check_authorize(params)
        hidden = "".join(f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">'
                         for name, value in params.items())
        people = "".join(
            f'<button name="user" value="{user_id}">Continue as {html.escape(user["global_name"] or user["username"])}'
            f' (@{html.escape(user["username"])})</button>'
            for user_id, user in self.users.items())
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Fake Discord</title>
<style>body{{font:16px system-ui;background:#313338;color:#fff;display:grid;place-items:center;min-height:90vh}}
main{{background:#2b2d31;padding:32px;border-radius:8px;width:420px}}button{{display:block;width:100%;margin:8px 0;
padding:12px;border:0;border-radius:4px;background:#5865f2;color:#fff;font-size:15px;cursor:pointer}}
button.cancel{{background:#4e5058}}</style></head>
<body><main><h1>Fake Discord</h1><p>Filter Lab wants to know who you are (scope: identify).</p>
<form method="post" action="/oauth2/authorize">{hidden}{people}
<button class="cancel" name="decision" value="cancel">Cancel</button></form></main></body></html>"""
        return web.Response(text=page, content_type="text/html")

    async def authorize_decision(self, request):
        form = dict(await request.post())
        params = {key: value for key, value in form.items() if key not in {"user", "decision"}}
        self._check_authorize(params)
        if form.get("decision") == "cancel":
            raise web.HTTPFound(self.cancel(self.authorize_url + "?" + urlencode(params)))
        raise web.HTTPFound(self._back(params, code=self.issue_code(params, int(form["user"]))))

    async def token(self, request):
        expected = "Basic " + base64.b64encode(f"{APPLICATION_ID}:{self.client_secret}".encode()).decode()
        if request.headers.get("Authorization") != expected:
            return web.json_response({"error": "invalid_client"}, status=401)
        form = dict(await request.post())
        grant = self.codes.pop(form.get("code", ""), None)
        if form.get("grant_type") != "authorization_code" or grant is None:
            return web.json_response({"error": "invalid_grant"}, status=400)
        if form.get("redirect_uri") != grant["redirect_uri"]:
            return web.json_response({"error": "invalid_grant"}, status=400)
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        if base64.urlsafe_b64encode(digest).decode().rstrip("=") != grant["challenge"]:
            return web.json_response({"error": "invalid_grant"}, status=400)
        token = secrets.token_urlsafe(24)
        self.tokens[token] = grant["user_id"]
        return web.json_response({"access_token": token, "token_type": "Bearer", "expires_in": 604800,
                                  "refresh_token": secrets.token_urlsafe(24), "scope": "identify"})

    async def me(self, request):
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and authorization[7:] in self.tokens:
            return web.json_response(self.users[self.tokens[authorization[7:]]])
        if authorization == f"Bot {self.bot_token}":
            return web.json_response({"id": str(BOT_ID), "username": "PosterFinderDev", "global_name": None,
                                      "avatar": None, "discriminator": "0", "bot": True})
        return web.json_response({"message": "401: Unauthorized", "code": 0}, status=401)

    # The bot's REST calls, as hikari makes them.

    def _bot(self, request):
        if request.headers.get("Authorization") != f"Bot {self.bot_token}":
            raise web.HTTPUnauthorized(text='{"message": "401: Unauthorized", "code": 0}',
                                       content_type="application/json")

    async def my_guilds(self, request):
        self._bot(request)
        after = int(request.query.get("after", "0"))
        return web.json_response([{
            "id": str(guild.id), "name": guild.name, "icon": None, "owner": False, "permissions": "0",
            "features": [], "approximate_member_count": len(guild.members),
            "approximate_presence_count": 0,
        } for guild in sorted(self.guilds.values(), key=lambda guild: guild.id) if guild.id > after])

    async def guild(self, request):
        self._bot(request)
        guild = self.guilds.get(int(request.match_info["guild"]))
        if guild is None:
            return _not_found(10004, "Unknown Guild")
        roles = [{"id": str(role_id), "name": "@everyone" if role_id == guild.id else f"role-{role_id}",
                  "color": 0, "hoist": False, "icon": None, "unicode_emoji": None, "position": index,
                  "permissions": str(permissions), "managed": False, "mentionable": False, "flags": 0}
                 for index, (role_id, permissions) in enumerate(guild.roles.items())]
        return web.json_response({
            "id": str(guild.id), "name": guild.name, "icon": None, "splash": None, "discovery_splash": None,
            "owner_id": str(guild.owner_id), "afk_channel_id": None, "afk_timeout": 300,
            "widget_enabled": False, "widget_channel_id": None, "verification_level": 0,
            "default_message_notifications": 0, "explicit_content_filter": 0, "roles": roles,
            "emojis": [], "stickers": [], "features": [], "mfa_level": 0, "application_id": None,
            "system_channel_id": None, "system_channel_flags": 0, "rules_channel_id": None,
            "max_presences": None, "max_members": 500000, "vanity_url_code": None, "description": None,
            "banner": None, "premium_tier": 0, "premium_subscription_count": 0, "preferred_locale": "en-US",
            "public_updates_channel_id": None, "max_video_channel_users": 25, "nsfw_level": 0,
        })

    async def member(self, request):
        self._bot(request)
        guild = self.guilds.get(int(request.match_info["guild"]))
        if guild is None:
            return _not_found(10004, "Unknown Guild")
        user_id = int(request.match_info["user"])
        if user_id not in guild.members:
            return _not_found(10007, "Unknown Member")
        return web.json_response({
            "user": self.users[user_id], "nick": None, "avatar": None, "roles": [str(role) for role in guild.members[user_id]],
            "joined_at": "2024-01-01T00:00:00+00:00", "premium_since": None, "deaf": False, "mute": False,
            "flags": 0, "pending": False, "communication_disabled_until": guild.timeouts.get(user_id),
        })

    async def application(self, request):
        self._bot(request)
        return web.json_response({
            "id": str(APPLICATION_ID), "name": "PosterFinderDev", "icon": None, "description": "",
            "bot_public": False, "bot_require_code_grant": False, "verify_key": "00" * 32, "flags": 0,
            "owner": {"id": "1", "username": "owner", "avatar": None, "discriminator": "0"},
            "approximate_guild_count": len(self.guilds), "approximate_user_install_count": 0,
        })

    async def avatar(self, request):
        colors = ["#5865F2", "#757E8A", "#3BA55C", "#FAA61A", "#ED4245", "#EB459F"]
        color = colors[sum(map(ord, request.match_info["name"])) % len(colors)]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" '
               f'fill="{color}"/><circle cx="32" cy="26" r="12" fill="#fff"/><rect x="14" y="42" width="36" '
               f'height="16" rx="8" fill="#fff"/></svg>')
        return web.Response(text=svg, content_type="image/svg+xml")

    # A page for changing members and roles while someone is signed in, to try revocation.

    async def control_page(self, request):
        rows = []
        for guild in self.guilds.values():
            for user_id, user in self.users.items():
                state = ("not a member" if user_id not in guild.members else
                         f"member, roles {sorted(guild.members[user_id])}")
                rows.append(
                    f"<tr><td>{html.escape(guild.name)}</td><td>{html.escape(user['username'])}</td><td>{state}</td>"
                    f'<td><form method="post"><input type="hidden" name="guild" value="{guild.id}">'
                    f'<input type="hidden" name="user" value="{user_id}">'
                    '<button name="action" value="remove">Remove from server</button>'
                    '<button name="action" value="member">Member without roles</button>'
                    '<button name="action" value="manager">Give Manage Channels role</button></form></td></tr>')
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Fake Discord control</title>
</head><body><h1>Fake Discord control</h1><p>Discord is {"down" if self.down else "up"}.</p>
<form method="post"><button name="action" value="toggle_down">Toggle Discord down</button></form>
<table border="1" cellpadding="6"><tr><th>Server</th><th>User</th><th>Now</th><th>Change</th></tr>{"".join(rows)}
</table></body></html>"""
        return web.Response(text=page, content_type="text/html")

    async def control(self, request):
        form = dict(await request.post())
        if form["action"] == "toggle_down":
            self.down = not self.down
        else:
            guild, user_id = self.guilds[int(form["guild"])], int(form["user"])
            if form["action"] == "remove":
                guild.members.pop(user_id, None)
            elif form["action"] == "member":
                guild.members[user_id] = []
            else:
                manager = next((role for role, bits in guild.roles.items()
                                if bits & PERMISSIONS["manage_channels"] and role != guild.id), None)
                if manager is None:
                    manager = max(guild.roles) + 1
                    guild.roles[manager] = PERMISSIONS["manage_channels"]
                guild.members[user_id] = [manager]
        raise web.HTTPFound("/fake")
