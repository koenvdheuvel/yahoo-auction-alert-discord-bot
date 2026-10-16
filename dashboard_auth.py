"""Discord sign-in for the dashboard.

DiscordOAuth runs Discord's OAuth2 code grant with only the `identify` scope, so the dashboard learns
who the person is and nothing else. DiscordGuilds then works out what they may open, using the
bot's own token: the servers the bot is in, the person's roles there and what those roles allow.
"""
import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
import logging
import re
from urllib.parse import urlencode

import aiohttp
import hikari

from commands.base import ADMIN_PERMISSION

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
API_URL = "https://discord.com/api/v10"
CDN_URL = "https://cdn.discordapp.com"
LOGIN_PATH = "/auth/discord"
# The redirect URI to register in the Discord Developer Portal is DASHBOARD_PUBLIC_URL + this path.
CALLBACK_PATH = LOGIN_PATH + "/callback"
# One access check, the server list and one member lookup per server, must finish in this time.
CHECK_SECONDS = 10
# Member lookups in different servers run side by side, at most this many at once.
CHECK_CONCURRENCY = 4
USER_AGENT = "AuctionBotDashboard (https://github.com/koenvdheuvel/yahoo-auction-alert-discord-bot, 1.0)"
AVATAR_HASH = re.compile(r"(a_)?[0-9a-f]{32}")
# Errors that mean Discord could not answer. Anything else is a bug and is not hidden.
UNAVAILABLE = (hikari.HTTPError, aiohttp.ClientError, OSError, TimeoutError)


class DiscordUnavailable(Exception):
    """Discord could not be reached or answered with an error, so access is unknown."""


class DiscordRefused(Exception):
    """Discord did not accept the sign-in, for example an expired or reused code."""


def describe(error):
    """A short description of a Discord failure for the logs, such as "InternalServerError 503"."""
    status = getattr(error, "status", None)
    return f"{type(error).__name__} {int(status)}" if status else type(error).__name__


def guild_permissions(user_id, owner_id, guild_id, role_permissions, member_role_ids, timed_out=False):
    """A member's server-wide permissions, worked out the way Discord works out base permissions.

    role_permissions maps every role ID in the server to what the role allows. The @everyone
    role has the server's own ID. Channel overwrites are not included here: signing in needs the
    permission for the whole server, and discord_directory adds a channel's overwrites for changes.
    """
    if user_id == owner_id:
        return hikari.Permissions.all_permissions()
    permissions = role_permissions.get(guild_id, hikari.Permissions.NONE)
    for role_id in member_role_ids:
        permissions |= role_permissions.get(role_id, hikari.Permissions.NONE)
    if permissions & hikari.Permissions.ADMINISTRATOR:
        return hikari.Permissions.all_permissions()
    if timed_out:
        # Discord takes every other permission away from a member in timeout.
        return permissions & (hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY)
    return permissions


def can_manage(permissions):
    """True when the permissions include the one the bot's management commands require."""
    return (permissions & ADMIN_PERMISSION) == ADMIN_PERMISSION


@dataclass(frozen=True)
class Member:
    """The person in one server: their roles and whether they are in timeout."""
    role_ids: tuple
    timed_out: bool = False


@dataclass(frozen=True)
class Access:
    """What one check found."""
    # Server ID to its name and icon, for every server where the person holds ADMIN_PERMISSION.
    guilds: dict
    # How many of the bot's servers the person is in, with or without the permission.
    member_of: int
    # Server ID to Member, for the servers in guilds. Changes to a channel check its overwrites with these.
    members: dict = field(default_factory=dict)


class DiscordGuilds:
    """Checks a person's servers with the bot's token.

    The bot has no members intent, so members always come from REST. The server list comes from
    REST too: right after the bot connects, the gateway cache does not have every server yet, and
    a missing server would wrongly deny access. Roles and the server owner come from the gateway
    cache, which role and server update events keep current, or from REST when it lacks them.
    """

    def __init__(self, rest=None, cache=None, *, timeout=CHECK_SECONDS):
        # Standalone mode creates its REST client once the event loop runs and sets it here.
        self.rest, self.cache, self.timeout = rest, cache, timeout
        self._application_id = None

    async def application_id(self):
        """The bot's application ID, which is also its OAuth2 client ID."""
        if self._application_id is None:
            try:
                async with asyncio.timeout(self.timeout):
                    self._application_id = int((await self.rest.fetch_application()).id)
            except UNAVAILABLE as error:
                raise DiscordUnavailable(f"The bot's application could not be read: {describe(error)}") from error
        return self._application_id

    async def check(self, user_id):
        try:
            async with asyncio.timeout(self.timeout):
                guilds = [guild async for guild in self.rest.fetch_my_guilds()]
                limit = asyncio.Semaphore(CHECK_CONCURRENCY)
                results = await asyncio.gather(*(self._check_guild(guild.id, user_id, limit) for guild in guilds),
                                               return_exceptions=True)
        except UNAVAILABLE as error:
            raise DiscordUnavailable(f"The access check did not finish: {describe(error)}") from error
        for result in results:
            # Any server that could not be checked makes the whole answer unknown, so nothing is
            # granted on a partial answer.
            if isinstance(result, UNAVAILABLE):
                raise DiscordUnavailable(f"A server could not be checked: {describe(result)}") from result
            if isinstance(result, BaseException):
                raise result
        allowed = {int(guild.id): _guild_json(guild) for guild, (_, manage, _) in zip(guilds, results) if manage}
        members = {int(guild.id): member for guild, (_, manage, member) in zip(guilds, results) if manage}
        return Access(allowed, sum(found for found, _, _ in results), members)

    async def _check_guild(self, guild_id, user_id, limit):
        """(is a member, holds ADMIN_PERMISSION, Member or None) for one server."""
        async with limit:
            try:
                member = await self.rest.fetch_member(guild_id, user_id)
            except hikari.NotFoundError:
                # Not in the server, or the bot has just left it.
                return False, False, None
            owner_id, roles = self._cached_roles(guild_id) or await self._fetched_roles(guild_id)
        found = Member(tuple(int(role) for role in member.role_ids), member.communication_disabled_until() is not None)
        permissions = guild_permissions(user_id, owner_id, guild_id, roles, found.role_ids, timed_out=found.timed_out)
        return True, can_manage(permissions), found

    def _cached_roles(self, guild_id):
        if self.cache is None:
            return None
        guild = self.cache.get_available_guild(guild_id)
        roles = self.cache.get_roles_view_for_guild(guild_id)
        # Every server has an @everyone role; without it the cache has no roles for the server.
        if guild is None or guild_id not in roles:
            return None
        return guild.owner_id, {role_id: role.permissions for role_id, role in roles.items()}

    async def _fetched_roles(self, guild_id):
        guild = await self.rest.fetch_guild(guild_id)
        return guild.owner_id, {role_id: role.permissions for role_id, role in guild.roles.items()}


def _guild_json(guild):
    icon = guild.make_icon_url(size=64)
    return {"id": str(guild.id), "name": guild.name, "icon_url": str(icon) if icon else None}


def code_challenge(verifier):
    """The PKCE S256 challenge for a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def _json(response):
    try:
        data = await response.json(content_type=None)
    except (ValueError, aiohttp.ContentTypeError):
        return {}
    return data if isinstance(data, dict) else {}


class DiscordOAuth:
    """Discord's OAuth2 code grant for the `identify` scope.

    The access token is used once, to read the person's ID, name and avatar, and is then revoked
    at Discord. It is not stored and not used to list the person's servers.

    PKCE is sent with every sign-in. Discord's OAuth2 page does not describe it, but Discord
    accepts S256 challenges. The state value and the login cookie protect the sign-in either way.
    """

    def __init__(self, client_secret, redirect_uri, *, authorize_url=AUTHORIZE_URL, api_url=API_URL,
                 cdn_url=CDN_URL, timeout=10):
        self.client_secret, self.redirect_uri = client_secret, redirect_uri
        self.authorize, self.api, self.cdn = authorize_url, api_url.rstrip("/"), cdn_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None

    @classmethod
    def from_settings(cls, settings, **urls):
        return cls(settings.dashboard_discord_client_secret, settings.dashboard_public_url + CALLBACK_PATH, **urls)

    def authorize_url(self, client_id, state, verifier):
        # No prompt=none: Discord does not document what it does for someone who never approved
        # the dashboard, so Discord shows its consent screen every time.
        return self.authorize + "?" + urlencode({
            "response_type": "code", "client_id": str(client_id), "scope": "identify",
            "redirect_uri": self.redirect_uri, "state": state,
            "code_challenge": code_challenge(verifier), "code_challenge_method": "S256",
        })

    async def identify(self, client_id, code, verifier):
        """Exchange the code and return the person's ID, display name, username and avatar."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout, headers={"User-Agent": USER_AGENT})
        client = {"Authorization": aiohttp.encode_basic_auth(str(client_id), self.client_secret)}
        try:
            async with self.session.post(self.api + "/oauth2/token", data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            }, headers=client) as response:
                body = await _json(response)
                if response.status in {400, 401}:
                    # invalid_grant: an expired or reused code. invalid_client: a wrong client secret.
                    error = body.get("error")
                    raise DiscordRefused(error if isinstance(error, str) and error.isidentifier()
                                         else f"token_status_{response.status}")
                token = body.get("access_token")
                if response.status != 200 or not isinstance(token, str):
                    raise DiscordUnavailable(f"The token request answered {response.status}")
            async with self.session.get(self.api + "/users/@me",
                                        headers={"Authorization": f"Bearer {token}"}) as response:
                user = await _json(response)
                if response.status == 401:
                    raise DiscordRefused("token_not_accepted")
                if response.status != 200:
                    raise DiscordUnavailable(f"The user request answered {response.status}")
        except (aiohttp.ClientError, TimeoutError) as error:
            raise DiscordUnavailable(f"Discord could not be reached: {describe(error)}") from error
        await self._revoke(token, client)
        identifier = user.get("id")
        if not isinstance(identifier, str) or not identifier.isdigit() or len(identifier) > 20:
            raise DiscordUnavailable("Discord sent a user without an ID")
        username = str(user.get("username") or "")[:64]
        name = str(user.get("global_name") or username)[:64]
        return {"id": identifier, "name": name, "username": username, "avatar_url": self.avatar_url(user)}

    async def _revoke(self, token, client):
        """End the token at Discord. Sign-in does not wait on this: a failure only means the token
        lives until Discord expires it."""
        try:
            async with self.session.post(self.api + "/oauth2/token/revoke", data={
                    "token": token, "token_type_hint": "access_token"}, headers=client) as response:
                if response.status != 200:
                    logger.info("discord_token_revoke_failed", extra={"fields": {"status": response.status}})
        except (aiohttp.ClientError, TimeoutError) as error:
            logger.info("discord_token_revoke_failed", extra={"fields": {"error": describe(error)}})

    def avatar_url(self, user):
        identifier, avatar = int(user["id"]), user.get("avatar")
        if isinstance(avatar, str) and AVATAR_HASH.fullmatch(avatar):
            return f"{self.cdn}/avatars/{identifier}/{avatar}.png?size=64"
        # People without an avatar get one of Discord's default ones.
        discriminator = str(user.get("discriminator") or "0")
        index = int(discriminator) % 5 if discriminator.isdigit() and discriminator != "0" else (identifier >> 22) % 6
        return f"{self.cdn}/embed/avatars/{index}.png"

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None
