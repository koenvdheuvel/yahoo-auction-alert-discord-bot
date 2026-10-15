import lightbulb
from commands.base import (
    ADMIN_PERMISSION, CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, management_hooks, respond,
)


class AllAlertsCommand(
    lightbulb.SlashCommand, name="allalerts", description="List alerts across this server's channels.",
    default_member_permissions=ADMIN_PERMISSION, contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS, hooks=management_hooks(),
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        alerts = await services.repository.list_alerts(
            channel_id=ctx.channel_id, guild_id=ctx.guild_id,
        )
        if not alerts:
            await respond(ctx, "You have no alerts in this server!", ephemeral=True)
            return
        await services.respond_lines(ctx, [
            f"<#{alert['channel_id']}> - {alert['search_query']}" for alert in alerts
        ], ephemeral=True)
