import lightbulb
from commands.base import BaseCommand
from models import Alert

class AlertsCommand(BaseCommand):
    def register(self):
        @self.bot.command
        @lightbulb.command("alerts", "List alerts for current channel")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def alerts(ctx: lightbulb.SlashContext) -> None:
            alerts = Alert.select().where(Alert.channel_id == ctx.channel_id)

            if all(False for _ in alerts):
                await ctx.respond("You have no alerts in this channel!")
                return

            alert_list = "\n".join([f"{alert.search_query}" for alert in alerts])
            await ctx.respond(alert_list or "None")
