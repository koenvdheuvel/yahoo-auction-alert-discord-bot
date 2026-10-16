import logging

import hikari
import lightbulb
from channel_maintenance import HISTORY_SCAN_LIMIT, add_cleanup_reactions
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, log_change, management_hooks, respond,
)


logger = logging.getLogger(__name__)


class ReactToCleanupCommand(
    lightbulb.SlashCommand, name="reacttocleanup",
    description="Add delete reactions to recent tracked item posts.",
    default_member_permissions=ADMIN_PERMISSION, contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS, hooks=management_hooks(),
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        bot_user = services.bot.get_me()
        if bot_user is None:
            await respond(ctx, "The bot is not connected yet. Try again shortly.", ephemeral=True)
            return
        try:
            added = await add_cleanup_reactions(services.bot.rest, services.repository, bot_user.id, ctx.channel_id)
        except hikari.ForbiddenError:
            logger.warning("cleanup_reactions_forbidden", exc_info=True,
                           extra={"fields": {"channel_id": int(ctx.channel_id)}})
            await respond(ctx, "I need permission to read history and add reactions.", ephemeral=True)
            return
        except Exception:
            logger.exception("cleanup_reactions_failed",
                             extra={"fields": {"channel_id": int(ctx.channel_id)}})
            await respond(ctx, "Could not finish adding reactions. See the bot logs for details.",
                          ephemeral=True)
            return
        log_change("cleanup_reactions_completed", ctx, added=added, history_limit=HISTORY_SCAN_LIMIT)
        await respond(ctx, f"Added delete reactions to {added} tracked item posts in the most recent "
                      f"{HISTORY_SCAN_LIMIT} channel messages.", ephemeral=True)
