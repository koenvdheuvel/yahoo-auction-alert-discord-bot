"""Run the dashboard with Discord sign-in against a fake Discord on this computer.

For trying the sign-in, the denials, the server list, the channel list, the two access levels
and revocation in a real browser without a Discord application. Use a copy of a database,
never the bot's own file:

    python -m devtools.dashboard_harness --database dashboard-scratch.db

Open http://127.0.0.1:9101. The fake Discord runs on http://localhost:9199, another site as
far as the browser is concerned, like discord.com is. Its page at /fake changes members and
roles, deletes channels, and can make Discord stop answering. Nothing here is used by the bot
or by dashboard.py.

Each server with searches in the database gets channels like a small server: a welcome channel,
the searches' channels under a category with two threads (one archived), and a category with a
channel only managers can view, one where managers may not change things, one where the bot
cannot add reactions, an announcement channel and a voice channel. One more server without
searches is added, so the server list has two.
"""
import argparse
import asyncio
from dataclasses import replace
import logging
from pathlib import Path

from aiohttp import web
import hikari

from config import Settings
from devtools.fake_discord import PERMISSIONS, FakeDiscord
from models import Alert, configure_database, create_tables
from observability import Metrics, configure_logging
from repositories import Repository
from dashboard import DashboardServer
from dashboard_auth import DiscordGuilds, DiscordOAuth
from discord_directory import ChannelDirectory

SECRET = "fake-client-secret-for-the-harness"
BOT_TOKEN = "fake-bot-token"
NAMES = ["Poster hunters", "Record shop", "Third server"]
CHANNELS = ["poster-alerts", "rhythm-games", "vinyl-drops", "figures", "goods", "rare-finds"]
# alice manages the first server, erin every server, bob is a member without the permission (so
# he only sees his own notifications), carol is in no server, and dave owns the last server.
USERS = [(1001, "alice", "Alice"), (1002, "bob", "Bob"), (1003, "carol", "Carol"), (1004, "dave", "Dave"),
         (1005, "erin", "Erin")]


def seed_channels(fake, guild_id, search_channels, manager):
    """Channels like a small server's, with the cases the channel list has to show."""
    ids = iter(range(guild_id + 100, guild_id + 200))
    bot_role = guild_id + 9
    deny = {name: PERMISSIONS[name] for name in ("view_channel", "manage_channels", "add_reactions")}
    fake.add_channel(guild_id, next(ids), "welcome", position=0)
    category = next(ids)
    fake.add_channel(guild_id, category, "SEARCHES", "category", position=0)
    for index, channel_id in enumerate(search_channels):
        fake.add_channel(guild_id, channel_id, CHANNELS[index % len(CHANNELS)], parent_id=category, position=index)
    if search_channels:
        fake.add_channel(guild_id, next(ids), "sold-out", "thread", parent_id=search_channels[0])
        fake.add_channel(guild_id, next(ids), "last-season", "thread", parent_id=search_channels[0], archived=True)
    category = next(ids)
    fake.add_channel(guild_id, category, "COMMUNITY", "category", position=1)
    fake.add_channel(guild_id, next(ids), "general", parent_id=category, position=0)
    fake.add_channel(guild_id, next(ids), "announcements", "announcement", parent_id=category, position=1)
    fake.add_channel(guild_id, next(ids), "staff", parent_id=category, position=2,
                     overwrites=[(guild_id, "role", 0, deny["view_channel"]), (manager, "role", deny["view_channel"], 0)])
    fake.add_channel(guild_id, next(ids), "read-only", parent_id=category, position=3,
                     overwrites=[(manager, "role", 0, deny["manage_channels"])])
    fake.add_channel(guild_id, next(ids), "quiet", parent_id=category, position=4,
                     overwrites=[(bot_role, "role", 0, deny["add_reactions"])])
    fake.add_channel(guild_id, next(ids), "Lounge", "voice", parent_id=category, position=5)


async def run(args):
    configure_logging("INFO", secrets=(SECRET, BOT_TOKEN))
    configure_database(args.database)
    create_tables()
    alerts = [alert for alert in Alert.select() if alert.guild_id is not None]
    guild_ids = sorted({alert.guild_id for alert in alerts})
    if not guild_ids:
        raise SystemExit("The database has no alerts with a server")
    # A server without searches, so the server list has more than one.
    guild_ids.append(guild_ids[-1] + 1000)

    # localhost, so the browser treats the fake as another site than the dashboard's 127.0.0.1, like
    # discord.com. Its fixed port is the same on both of localhost's addresses.
    fake = FakeDiscord(client_secret=SECRET, bot_token=BOT_TOKEN, host="localhost", port=args.discord_port)
    for user_id, username, name in USERS:
        fake.add_user(user_id, username, name)
    for index, guild_id in enumerate(guild_ids):
        last = index == len(guild_ids) - 1
        guild = fake.add_guild(guild_id, NAMES[index] if index < len(NAMES) else f"Server {index + 1}",
                               owner_id=1004 if last else 1)
        manager = guild_id + 1
        guild.roles[manager] = PERMISSIONS["manage_channels"]
        guild.members.update({1002: [], 1005: [manager]})
        if index == 0:
            guild.members[1001] = [manager]
        if last:
            guild.members[1004] = []
        seed_channels(fake, guild_id, sorted({alert.channel_id for alert in alerts if alert.guild_id == guild_id}),
                      manager)
    await fake.start()

    settings = replace(Settings(), token=BOT_TOKEN, database_path=args.database, dashboard_host="127.0.0.1",
                       dashboard_port=args.port, dashboard_public_url=f"http://127.0.0.1:{args.port}",
                       dashboard_discord_client_secret=SECRET)
    rest_app = hikari.RESTApp(url=fake.api_url, max_retries=0)
    await rest_app.start()
    rest = rest_app.acquire(BOT_TOKEN, hikari.TokenType.BOT)
    rest.start()
    oauth = DiscordOAuth.from_settings(settings, authorize_url=fake.authorize_url, api_url=fake.api_url,
                                       cdn_url=fake.base_url)
    repository = Repository(Metrics())
    await repository.start()
    # The REST path, as the standalone dashboard uses it. Channel answers are kept for a few seconds,
    # so changes on the /fake page show up quickly.
    server = DashboardServer(settings, repository, repository.metrics, directory=ChannelDirectory(rest, ttl=3, channel_ttl=3),
                             guild_access=DiscordGuilds(rest), oauth=oauth, access_seconds=args.recheck)
    runner = web.AppRunner(server.application(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    logging.getLogger(__name__).info("harness_ready", extra={"fields": {
        "dashboard": settings.dashboard_public_url, "fake_discord": fake.base_url + "/fake",
        "recheck_seconds": args.recheck}})
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await server.close()
        await rest.close()
        await rest_app.close()
        await fake.close()
        await repository.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="A copy of the bot's database")
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--discord-port", type=int, default=9199)
    parser.add_argument("--recheck", type=float, default=300, help="Seconds between access checks (default 300)")
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.error("The database does not exist")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
