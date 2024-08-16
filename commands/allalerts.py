import lightbulb
from commands.base import BaseCommand
from models import Alert
from lightbulb.utils import pag, nav

class AllAlertsCommand(BaseCommand):
    def register(self):
        @self.bot.command
        @lightbulb.command("allalerts", "List alerts for all channels")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def allalerts(ctx: lightbulb.SlashContext) -> None:
            # Fetch all alerts and group them by channel_id
            alerts = Alert.select().order_by(Alert.channel_id)
            if not alerts:
                await ctx.respond("You have no alerts!")
                return

            paginated_alerts = pag.StringPaginator()
            for alert in alerts:
                paginated_alerts.add_line(f"<#{alert.channel_id}> - {alert.search_query}")
            navigation = nav.ButtonNavigator(paginated_alerts.build_pages())
            await navigation.run(ctx)

