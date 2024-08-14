import lightbulb
from commands.base import BaseCommand
from models import Alert
class RegisterCommand(BaseCommand):
    def register(self):
        @self.bot.command
        @lightbulb.option("search_query", "search query of the item to register.", required=True)
        @lightbulb.command(
            "register", "Register a new search query for a specific item.", pass_options=True
        )
        @lightbulb.implements(lightbulb.SlashCommand)
        async def register(ctx: lightbulb.SlashContext, search_query: str) -> None:
            if Alert().select().where(Alert.search_query == search_query).exists():
                await ctx.respond(f"Alert for **{search_query}** already exists!")

            alert = Alert.create(
                channel_id=ctx.channel_id,
                search_query=search_query,
            )

            await ctx.respond(f"Registered alert for **{search_query}**!")
