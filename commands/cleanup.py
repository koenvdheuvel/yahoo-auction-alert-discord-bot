import logging

import hikari
import lightbulb
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, HISTORY_SCAN_LIMIT,
    is_bot_post, log_change, management_hooks, respond,
)


logger = logging.getLogger(__name__)
MAX_DELETE_COUNT = 100


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
        deleted = 0
        try:
            async for message in services.bot.rest.fetch_messages(ctx.channel_id).limit(HISTORY_SCAN_LIMIT):
                if not is_bot_post(message, bot_user.id):
                    continue
                try:
                    await services.bot.rest.delete_message(ctx.channel_id, message.id)
                except hikari.NotFoundError:
                    await services.repository.mark_message_deleted(ctx.channel_id, message.id)
                    continue
                await services.repository.mark_message_deleted(ctx.channel_id, message.id)
                deleted += 1
                if deleted >= count:
                    break
        except hikari.ForbiddenError:
            logger.warning("cleanup_forbidden", exc_info=True,
                           extra={"fields": {"channel_id": int(ctx.channel_id)}})
            await respond(ctx, f"Deleted {deleted} posts. I need permission to read history and "
                          "delete messages.", ephemeral=True)
            return
        except Exception:
            logger.exception("cleanup_failed", extra={"fields": {"channel_id": int(ctx.channel_id)}})
            await respond(ctx, f"Deleted {deleted} posts before an error. See the bot logs for details.",
                          ephemeral=True)
            return
        log_change("cleanup_completed", ctx, deleted=deleted, history_limit=HISTORY_SCAN_LIMIT)
        await respond(ctx, f"Deleted {deleted} bot posts from the most recent {HISTORY_SCAN_LIMIT} "
                      "channel messages.", ephemeral=True)
