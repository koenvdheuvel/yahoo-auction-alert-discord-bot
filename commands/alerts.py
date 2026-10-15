import lightbulb
from commands.base import CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, read_hooks, respond


class AlertsCommand(
    lightbulb.SlashCommand, name="alerts", description="List alerts in this channel.",
    contexts=GUILD_CONTEXTS, integration_types=GUILD_INSTALLS, hooks=read_hooks(),
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        alerts = await services.repository.list_alerts(channel_id=ctx.channel_id)
        if not alerts:
            await respond(ctx, "You have no alerts in this channel!")
            return
        await services.respond_lines(ctx, [alert["search_query"] for alert in alerts])
