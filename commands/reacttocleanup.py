import logging

import hikari
import lightbulb
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, HISTORY_SCAN_LIMIT,
    is_bot_post, log_change, management_hooks, respond,
)


logger = logging.getLogger(__name__)


async def add_reaction_to_bot_messages(services, channel_id):
    bot_user = services.bot.get_me()
    if bot_user is None:
        return 0
    added = 0
    async for message in services.bot.rest.fetch_messages(channel_id).limit(HISTORY_SCAN_LIMIT):
        if not is_bot_post(message, bot_user.id):
            continue
        if await services.repository.lookup_message(channel_id, message.id) is None:
            continue
        try:
            await services.bot.rest.add_reaction(channel_id, message.id, "🗑️")
        except hikari.NotFoundError:
            await services.repository.mark_message_deleted(channel_id, message.id)
            continue
        added += 1
    return added


class ReactToCleanupCommand(
    lightbulb.SlashCommand, name="reacttocleanup",
    description="Add delete reactions to recent tracked item posts.",
    default_member_permissions=ADMIN_PERMISSION, contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS, hooks=management_hooks(),
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        try:
            added = await add_reaction_to_bot_messages(services, ctx.channel_id)
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
