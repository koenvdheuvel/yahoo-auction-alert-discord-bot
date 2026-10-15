import lightbulb
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, log_change,
    management_hooks, respond, search_query_autocomplete,
)


class UnregisterCommand(
    lightbulb.SlashCommand, name="unregister", description="Remove a search alert from this channel.",
    default_member_permissions=ADMIN_PERMISSION, contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS, hooks=management_hooks(),
):
    search_query = lightbulb.string(
        "search_query", "Search query to remove from this channel.",
        autocomplete=search_query_autocomplete,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        search_query = self.search_query.strip()
        if not await services.repository.unregister_alert(ctx.channel_id, search_query):
            await respond(ctx, f"Alert for **{search_query}** does not exist in this channel!",
                          ephemeral=True)
            return
        log_change("alert_unregistered", ctx)
        await respond(ctx, f"Unregistered alert for **{search_query}**!", ephemeral=True)
