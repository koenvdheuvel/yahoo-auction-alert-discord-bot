import lightbulb
from commands.base import BaseCommand
from models import Alert
import hikari

class UnregisterCommand(BaseCommand):
    def register(self):
        async def _search_query_autocomplete(option: hikari.CommandInteractionOption, interaction: hikari.AutocompleteInteraction):
            print(option.value)
            if not isinstance(option.value, str):
                option.value = str(option.value)

            alerts = Alert.select(Alert.search_query).where(Alert.search_query.contains(option.value)).limit(25)
            return [alert.search_query for alert in alerts]

        @self.bot.command
        @lightbulb.option(
            "search_query",
            "Search_query of the alert to delete.",
            required=True,
            autocomplete=_search_query_autocomplete,
        )
        @lightbulb.command(
            "unregister", "Delete an alert", pass_options=True
        )
        @lightbulb.implements(lightbulb.SlashCommand)
        async def unregister(ctx: lightbulb.SlashContext, search_query: str) -> None:
            try:
                alert = Alert.get(Alert.search_query == search_query)
            except Alert.DoesNotExist:
                await ctx.respond(f"Alert for **{search_query}** does not exist!")
                return

            # Delete the alert
            alert.delete_instance()
            await ctx.respond(f"Unregistered alert for **{search_query}**!")
