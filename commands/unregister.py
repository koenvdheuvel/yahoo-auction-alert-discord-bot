import lightbulb
from commands.base import BaseCommand
from models import Alert

class UnregisterCommand(BaseCommand):
    def register(self):
        @self.bot.command
        @lightbulb.option("name", "Name of the item to delete.", required=True)
        @lightbulb.command(
            "unregister", "Delete an alert", pass_options=True
        )
        @lightbulb.implements(lightbulb.SlashCommand)
        async def unregister(ctx: lightbulb.SlashContext, name: str) -> None:
            try:
                alert = Alert.get(Alert.search_query == name)
            except Alert.DoesNotExist:
                await ctx.respond(f"Alert for **{name}** does not exist!")
                return

            # Delete the alert
            alert.delete_instance()
            await ctx.respond(f"Unregistered alert for **{name}**!")
