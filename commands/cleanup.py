import logging

import hikari
import lightbulb
from channel_maintenance import HISTORY_SCAN_LIMIT, MAX_DELETE_COUNT, Progress, delete_recent_bot_posts
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, log_change, management_hooks, respond,
)


logger = logging.getLogger(__name__)


class CleanupCommand(
    lightbulb.SlashCommand, name="cleanup", description="Delete recent bot posts in this channel.",
    default_member_permissions=ADMIN_PERMISSION, contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS, hooks=management_hooks(),
):
    count = lightbulb.integer(
        "count", "Maximum number of recent bot posts to delete (1–100).", default=10,
        min_value=1, max_value=MAX_DELETE_COUNT,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        count = self.count
        if not 1 <= count <= MAX_DELETE_COUNT:
            await respond(ctx, f"Count must be between 1 and {MAX_DELETE_COUNT}.", ephemeral=True)
            return
        bot_user = services.bot.get_me()
        if bot_user is None:
            await respond(ctx, "The bot is not connected yet. Try again shortly.", ephemeral=True)
            return
        progress = Progress()
        try:
            await delete_recent_bot_posts(services.bot.rest, services.repository, bot_user.id, ctx.channel_id,
                                          count, progress)
        except hikari.ForbiddenError:
            logger.warning("cleanup_forbidden", exc_info=True,
                           extra={"fields": {"channel_id": int(ctx.channel_id)}})
            await respond(ctx, f"Deleted {progress.done} posts. I need permission to read history and "
                          "delete messages.", ephemeral=True)
            return
        except Exception:
            logger.exception("cleanup_failed", extra={"fields": {"channel_id": int(ctx.channel_id)}})
            await respond(ctx, f"Deleted {progress.done} posts before an error. See the bot logs for details.",
                          ephemeral=True)
            return
        log_change("cleanup_completed", ctx, deleted=progress.done, history_limit=HISTORY_SCAN_LIMIT)
        await respond(ctx, f"Deleted {progress.done} bot posts from the most recent {HISTORY_SCAN_LIMIT} "
                      "channel messages.", ephemeral=True)
