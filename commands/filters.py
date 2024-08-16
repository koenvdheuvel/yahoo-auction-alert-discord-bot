import lightbulb
import hikari
from commands.base import BaseCommand
from models import Filter, Alert
from peewee import fn, JOIN

class FilterCommands(BaseCommand):
    def register(self):
        async def _search_query_autocomplete(option: hikari.CommandInteractionOption, interaction: hikari.AutocompleteInteraction):
            if not isinstance(option.value, str):
                option.value = str(option.value)

            alerts = Alert.select(Alert.search_query).where(Alert.search_query.contains(option.value)).limit(25)

            return [alert.search_query for alert in alerts]

        # Get all alerts and create a list of the search query values
        @self.bot.command
        @lightbulb.command("filters", "Manage filters")
        @lightbulb.implements(lightbulb.SlashCommandGroup)
        async def filters(_: lightbulb.SlashContext) -> None:
            pass
        
        @filters.child
        @lightbulb.command("list", "List search queries with filters configured")
        @lightbulb.implements(lightbulb.SlashSubCommand)
        async def list(ctx: lightbulb.SlashContext) -> None:
            query = (Alert
                     .select(Alert, fn.Count(Filter.id).alias('filter_count'))
                     .join(Filter, JOIN.LEFT_OUTER)
                     .group_by(Alert)
                     .having(fn.Count(Filter.id) > 0))

            # Process the results
            if not query:
                await ctx.respond("You have no alerts with filters!")
                return
            
            # Output a list of search queries with the number of filters
            message = "\n".join(f"- <#{alert.channel_id}> - {alert.search_query} - (**{alert.filter_count}** filters)" for alert in query)
            await ctx.respond(message)

        @filters.child
        @lightbulb.option(
            "search_query", "Which search query to get filters for",
            required=True,
            autocomplete=_search_query_autocomplete,
        )
        @lightbulb.command("get", "List all filters", pass_options=True)
        @lightbulb.implements(lightbulb.SlashSubCommand)
        async def get(ctx: lightbulb.SlashContext, search_query: str) -> None:
            # Combine query to fetch alert and related filters in one go
            alert = (Alert
                    .select()
                    .join(Filter, JOIN.LEFT_OUTER)
                    .where(Alert.search_query == search_query)
                    .group_by(Alert)
                    .having(fn.Count(Filter.id) > 0)).get_or_none()
            
            # Check if any filters are returned, indicating the alert exists
            if not alert:
                await ctx.respond(f"Alert for **{search_query}** does not exist or has no filters!")
                return
            
            # Build the response message with filter details and a header
            message = f"Filters for **{search_query}**:\n"
            for filter in alert.filters:
                message += f"- **{filter.id}** - {filter.type} - **{filter.value}** - {'Blacklist' if filter.inverse else 'Whitelist'}\n"
        
            await ctx.respond(message)
            
        @filters.child
        @lightbulb.option(
            "search_query",
            "search query of the item to filter on.",
            required=True,
            autocomplete=_search_query_autocomplete,
            type=str,
        )
        @lightbulb.option(
            "method",
            "Filter method", 
            required=True,
            choices=["regex", "text"],
            type=str,
        )
        @lightbulb.option("value", "Either text or Regex Value", required=True)
        @lightbulb.option(
            "type", 
            "Filter type",
            default="blacklist",
            choices=["blacklist", "whitelist"],
            type=str,
        )
        @lightbulb.command(
            "add", "Register a new filter", pass_options=True
        )
        @lightbulb.implements(lightbulb.SlashSubCommand)
        async def add(
            ctx: lightbulb.SlashContext,
            value: str,
            search_query: str,
            method: str,
            type: str,
        ) -> None:
            alert = Alert.select().where(Alert.search_query == search_query).get_or_none()
            if alert is None:
                await ctx.respond(f"Alert for **{search_query}** does not exist!")
                return
            
            filter = Filter.create(
                alert=alert,
                type=type,
                value=value,
                inverse=type == "blacklist",
            )
            await ctx.respond(f"Registered filter with id **{filter.id}** for **{search_query}**!")

        filter_ids = Filter.select(Filter.id)
        @filters.child
        # Method must be one of the following: "regex", "text"
        @lightbulb.option(
            "id", "Filter ID to delete", 
            required=True,
            choices=[filter.id for filter in filter_ids],
            type=int,
        )
        @lightbulb.command(
            "delete", "Remove a filter", pass_options=True
        )
        @lightbulb.implements(lightbulb.SlashSubCommand)
        async def delete(ctx: lightbulb.SlashContext, id: int) -> None:
            filter = Filter.select().where(Filter.id == ctx.options.id).get_or_none()
            if filter is None:
                await ctx.respond(f"Filter with id **{ctx.options.id}** does not exist!")
                return
           
            filter.delete_instance()
            await ctx.respond(f"Deleted filter with id **{filter.id}**")

