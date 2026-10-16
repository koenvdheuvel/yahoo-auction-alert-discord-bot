"""Run Filter Lab with Discord sign-in against a fake Discord on this computer.

For trying the sign-in, the denials, the server picker and revocation in a real browser
without a Discord application. Use a copy of a database, never the bot's own file:

    python -m devtools.filter_lab_harness --database filterlab-scratch.db

Open http://127.0.0.1:9101. The fake Discord runs on http://localhost:9199, another site as
far as the browser is concerned, like discord.com is. Its page at /fake changes members and
roles, and can make Discord stop answering. Nothing here is used by the bot or by review.py.
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
from review import ReviewServer
from review_auth import DiscordGuilds, DiscordOAuth

SECRET = "fake-client-secret-for-the-harness"
BOT_TOKEN = "fake-bot-token"
NAMES = ["Poster hunters", "Record shop", "Third server"]
# alice manages the first server, erin every server, bob is a member without the permission,
# carol is in no server, and dave owns the last server.
USERS = [(1001, "alice", "Alice"), (1002, "bob", "Bob"), (1003, "carol", "Carol"), (1004, "dave", "Dave"),
         (1005, "erin", "Erin")]


async def run(args):
    configure_logging("INFO", secrets=(SECRET, BOT_TOKEN))
    configure_database(args.database)
    create_tables()
    guild_ids = sorted({alert.guild_id for alert in Alert.select() if alert.guild_id is not None})
    if not guild_ids:
        raise SystemExit("The database has no alerts with a server")

    fake = FakeDiscord(client_secret=SECRET, bot_token=BOT_TOKEN, port=args.discord_port)
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
    await fake.start()

    settings = replace(Settings(), token=BOT_TOKEN, database_path=args.database, review_host="127.0.0.1",
                       review_port=args.port, review_public_url=f"http://127.0.0.1:{args.port}",
                       review_discord_client_secret=SECRET)
    rest_app = hikari.RESTApp(url=fake.api_url, max_retries=0)
    await rest_app.start()
    rest = rest_app.acquire(BOT_TOKEN, hikari.TokenType.BOT)
    rest.start()
    oauth = DiscordOAuth.from_settings(settings, authorize_url=fake.authorize_url, api_url=fake.api_url,
                                       cdn_url=fake.base_url)
    repository = Repository(Metrics())
    await repository.start()
    server = ReviewServer(settings, repository, repository.metrics, guild_access=DiscordGuilds(rest), oauth=oauth,
                          access_seconds=args.recheck)
    runner = web.AppRunner(server.application(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    logging.getLogger(__name__).info("harness_ready", extra={"fields": {
        "filter_lab": settings.review_public_url, "fake_discord": fake.base_url + "/fake",
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
    parser.add_argument("--database", required=True, help="A copy of a Filter Lab database")
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
