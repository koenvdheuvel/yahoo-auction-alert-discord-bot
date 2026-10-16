"""Application composition. Importing this module never starts a bot or reads a token."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

import hikari
import lightbulb

if TYPE_CHECKING:
    from observability import Metrics
    from repositories import Repository
    from runtime import Runtime


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApplicationServices:
    repository: Repository
    runtime: Runtime
    metrics: Metrics
    commands: lightbulb.Client


class ApplicationBot(hikari.GatewayBot):
    """Hikari gateway with explicitly owned application services."""
    __slots__ = ("services",)
    services: ApplicationServices


def load_commands(bot, client, repository):
    # Explicit registration makes startup independent of cwd/module search path.
    from commands import register_commands

    register_commands(client, bot, repository)


def create_application(settings=None):
    """Validate configuration, migrate SQLite and assemble one bot process.

    No network calls or asyncio tasks are created here. Pass Settings explicitly
    for tests; otherwise dotenv is loaded before environment/database binding.
    """
    import dotenv
    from config import Settings
    from delivery import DeliveryWorker
    from models import configure_database, create_tables
    from observability import Metrics, configure_logging
    from processors.hikari_event import HikariEventProcessor
    from providers import HttpClient, PROVIDERS
    from repositories import Repository
    from review import ReviewServer
    from review_auth import DiscordGuilds
    from runtime import Runtime
    from storechecker import Ingestion

    if settings is None:
        dotenv.load_dotenv()
        settings = Settings.from_env()
    if not settings.token:
        raise ValueError("BOT_TOKEN is required")
    configure_logging(settings.log_level, secrets=(
        settings.token, settings.review_token, settings.review_discord_client_secret))
    configure_database(settings.database_path)
    create_tables()
    metrics = Metrics()
    bot = ApplicationBot(settings.token, logs=None, banner=None,
                         intents=hikari.Intents.GUILDS | hikari.Intents.GUILD_MESSAGE_REACTIONS)
    client = lightbulb.client_from_app(bot)
    repository = Repository(metrics)
    http = HttpClient(settings, metrics)
    ingestion = Ingestion(repository, metrics, settings)
    delivery = DeliveryWorker(bot, repository, metrics, settings)
    providers = {source: PROVIDERS[source](http, settings) for source in settings.enabled_sources}

    def channel_names(channel_ids):
        """Filter Lab shows channel names from the gateway cache instead of bare IDs."""
        names = {}
        for channel_id in channel_ids:
            channel = bot.cache.get_guild_channel(int(channel_id)) or bot.cache.get_thread(int(channel_id))
            if channel is not None and channel.name:
                names[channel_id] = channel.name
        return names

    # Discord sign-in checks people's servers and roles with the bot's REST client and cache.
    guild_access = DiscordGuilds(bot.rest, bot.cache) if settings.discord_sign_in else None
    review = ReviewServer(settings, repository, metrics, channel_names=channel_names, bot_running=True,
                          guild_access=guild_access)
    runtime = Runtime(bot, settings, repository, http, ingestion, delivery, providers, metrics,
                      review_server=review)
    bot.services = ApplicationServices(repository, runtime, metrics, client)
    processor = HikariEventProcessor()
    load_commands(bot, client, repository)

    async def startup_failed():
        logger.exception("runtime_startup_failed")
        runtime.failure = RuntimeError("Runtime startup failed; inspect structured logs")
        runtime.health.failed_worker = "startup"
        await bot.close()

    @bot.listen(hikari.StartingEvent)
    async def on_starting(event):
        try:
            await runtime.prepare()
        except asyncio.CancelledError:
            raise
        except Exception:
            await startup_failed()

    @bot.listen(hikari.StartedEvent)
    async def on_started(event):
        runtime.set_expected_shards(bot.shards.keys())
        try:
            await client.start()
            await runtime.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            await startup_failed()

    # Alerts saved before servers were recorded get their server from its channels. Discord
    # sends a server's channels after the bot connects (StartedEvent comes before them), and
    # again when the bot joins a server.
    @bot.listen(hikari.GuildAvailableEvent)
    @bot.listen(hikari.GuildJoinEvent)
    async def on_guild_available(event):
        channels = {int(channel_id): int(event.guild_id)
                    for channel_id in (*event.channels.keys(), *event.threads.keys())}
        try:
            await repository.reconcile_guilds(channels)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("guild_reconcile_failed", extra={"fields": {"guild_id": int(event.guild_id)}})

    @bot.listen(hikari.StoppingEvent)
    async def on_stopping(event):
        try:
            await client.stop()
        finally:
            await runtime.close()

    @bot.listen(hikari.ShardConnectedEvent)
    async def on_connected(event):
        runtime.set_connected(event.shard.id)

    @bot.listen(hikari.ShardDisconnectedEvent)
    async def on_disconnected(event):
        runtime.set_disconnected(event.shard.id)

    @bot.listen(hikari.Event)
    async def on_event(event):
        try:
            await processor.process_event(event, bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            metrics.reaction_errors.inc()
            logger.exception("reaction_handler_failed", extra={"fields": {
                "event_type": type(event).__name__, "channel_id": getattr(event, "channel_id", None),
                "message_id": getattr(event, "message_id", None),
            }})

    from commands.base import GuildOnlyError

    @client.error_handler
    async def on_command_error(error: lightbulb.exceptions.ExecutionPipelineFailedException) -> bool:
        context = error.context
        denied = bool(error.causes) and all(
            isinstance(cause, (GuildOnlyError, lightbulb.prefab.MissingRequiredPermission))
            for cause in error.causes
        )
        metrics.command_errors.labels("denied" if denied else "error").inc()
        if denied:
            message = "You do not have permission to run this command here."
        else:
            for cause in error.causes or [error]:
                logger.error("command_failed", exc_info=(type(cause), cause, cause.__traceback__),
                             extra={"fields": {"channel_id": context.channel_id}})
            message = "The command failed. Please try again; the error has been logged."
        try:
            await context.respond(message, ephemeral=True, mentions_everyone=False,
                                  user_mentions=False, role_mentions=False)
        except Exception:
            logger.exception("command_error_response_failed")
        return True

    return bot


def main():
    import hikari

    bot = create_application()
    bot.run(propagate_interrupts=True, asyncio_debug=False, check_for_updates=False,
            activity=hikari.Activity(name="Posters", type=hikari.ActivityType.WATCHING))
    if bot.services.runtime.failure is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
