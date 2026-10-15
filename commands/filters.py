from collections import Counter
import re

import lightbulb
from commands.base import (
    CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, log_change, management_hooks,
    read_hooks, respond, search_query_autocomplete,
)


filters_group = lightbulb.Group(
    "filters", "Manage filters in this channel.", contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS,
)


@filters_group.register
class FilterListCommand(
    lightbulb.SlashCommand, name="list", description="List this channel's alerts with filters.",
    hooks=read_hooks(),
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        rows = await services.repository.list_filters(ctx.channel_id)
        if not rows:
            await respond(ctx, "You have no alerts with filters in this channel!")
            return
        counts = Counter(row["search_query"] for row in rows)
        await services.respond_lines(ctx, [
            f"- {query} - **{count}** filters" for query, count in sorted(counts.items())
        ])


@filters_group.register
class FilterGetCommand(
    lightbulb.SlashCommand, name="get", description="Show filters for an alert in this channel.",
    hooks=read_hooks(),
):
    search_query = lightbulb.string(
        "search_query", "Search query to show filters for.", autocomplete=search_query_autocomplete,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        rows = await services.repository.list_filters(ctx.channel_id, self.search_query)
        if not rows:
            await respond(ctx, f"Alert for **{self.search_query}** does not exist or has no "
                          "filters in this channel!")
            return
        lines = [f"Filters for **{self.search_query}**:"]
        for row in rows:
            state = "enabled" if row["enabled"] else "disabled: select a matcher by replacing this filter"
            lines.append(
                f"- **{row['id']}** - {row['method'] or 'unset'} - {row['type']} - "
                f"{row['value']} - {state}"
            )
        await services.respond_lines(ctx, lines)


@filters_group.register
class FilterAddCommand(
    lightbulb.SlashCommand, name="add", description="Add a filter to an alert in this channel.",
    hooks=management_hooks(),
):
    search_query = lightbulb.string(
        "search_query", "Alert in this channel to filter.", autocomplete=search_query_autocomplete,
    )
    method = lightbulb.string(
        "method", "How to match the listing title.",
        choices=[lightbulb.Choice("regex", "regex"), lightbulb.Choice("text", "text")],
    )
    value = lightbulb.string(
        "value", "Text or regular expression to match.", min_length=1, max_length=1000,
    )
    policy = lightbulb.string(
        "type", "Blacklist excludes matches; whitelist requires a match.", default="blacklist",
        choices=[lightbulb.Choice("blacklist", "blacklist"), lightbulb.Choice("whitelist", "whitelist")],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        try:
            filter_id = await services.repository.add_filter(
                ctx.channel_id, self.search_query, self.method, self.policy, self.value,
            )
        except (ValueError, re.error) as exc:
            await respond(ctx, f"Invalid filter: {exc}", ephemeral=True)
            return
        if filter_id is None:
            await respond(ctx, f"Alert for **{self.search_query}** does not exist in this channel!",
                          ephemeral=True)
            return
        log_change("filter_registered", ctx, filter_id=filter_id, method=self.method, policy=self.policy)
        await respond(ctx, f"Registered filter **{filter_id}** for **{self.search_query}**!", ephemeral=True)


@filters_group.register
class FilterDeleteCommand(
    lightbulb.SlashCommand, name="delete", description="Delete a filter from this channel.",
    hooks=management_hooks(),
):
    filter_id = lightbulb.integer("id", "Filter ID from /filters get.", min_value=1)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        if not await services.repository.delete_filter(ctx.channel_id, self.filter_id):
            await respond(ctx, f"Filter **{self.filter_id}** does not exist in this channel!",
                          ephemeral=True)
            return
        log_change("filter_deleted", ctx, filter_id=self.filter_id)
        await respond(ctx, f"Deleted filter **{self.filter_id}**.", ephemeral=True)
