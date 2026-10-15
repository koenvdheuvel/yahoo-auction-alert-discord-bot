import lightbulb
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS,
    log_change, management_hooks, respond,
)


class RegisterCommand(
    lightbulb.SlashCommand, name="register", description="Register a search alert in this channel.",
    default_member_permissions=ADMIN_PERMISSION, contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS, hooks=management_hooks(),
):
    search_query = lightbulb.string(
        "search_query", "Search query to monitor in this channel.", min_length=1, max_length=100,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        search_query = self.search_query.strip()
        if not search_query:
            await respond(ctx, "Enter a non-empty search query.", ephemeral=True)
            return
        created = await services.repository.register_alert(
            ctx.channel_id, search_query, guild_id=ctx.guild_id,
        )
        if not created:
            await respond(ctx, f"Alert for **{search_query}** already exists in this channel!",
                          ephemeral=True)
            return
        log_change("alert_registered", ctx)
        await respond(ctx, f"Registered alert for **{search_query}**!", ephemeral=True)
