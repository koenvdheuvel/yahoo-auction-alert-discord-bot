"""/marketplaces: which marketplaces each alert in this channel checks."""
import lightbulb

from commands.base import (
    CommandServices, GUILD_CONTEXTS, GUILD_INSTALLS, log_change, management_hooks, read_hooks, respond,
    search_query_autocomplete,
)
from marketplaces import BY_SOURCE, MARKETPLACES


marketplaces_group = lightbulb.Group(
    "marketplaces", "Choose the marketplaces each alert in this channel checks.", contexts=GUILD_CONTEXTS,
    integration_types=GUILD_INSTALLS,
)
MARKETPLACE_CHOICES = [lightbulb.Choice(marketplace.name, marketplace.source) for marketplace in MARKETPLACES]


def describe(sources, searched):
    """'Mercari, Rakuma (off for the whole bot)'. searched: the marketplaces the bot searches at all."""
    if not sources:
        return "no marketplace, so it posts nothing"
    return ", ".join(BY_SOURCE[source].name + ("" if source in searched else " (off for the whole bot)")
                     for source in sources)


async def change(ctx, services, search_query, source, enabled):
    search_query = search_query.strip()
    result = await services.repository.set_alert_source(ctx.channel_id, search_query, source, enabled)
    name = BY_SOURCE[source].name
    if result is None:
        await respond(ctx, f"Alert for **{search_query}** does not exist in this channel!", ephemeral=True)
        return
    if not result["turned_on"] and not result["turned_off"]:
        await respond(ctx, f"**{search_query}** already {'checks' if enabled else 'skips'} {name}.",
                      ephemeral=True)
        return
    log_change("alert_sources_changed", ctx, alert_id=result["alert_id"], turned_on=result["turned_on"],
               turned_off=result["turned_off"])
    if not enabled:
        await respond(ctx, f"**{search_query}** no longer checks {name}. Its posts stay.", ephemeral=True)
        return
    text = (f"**{search_query}** now checks {name}. Its next check saves the listings there without "
            "posting them; after that, new listings are posted.")
    if source not in services.enabled_sources:
        text += f" The bot does not search {name} at the moment, so this starts when it does."
    await respond(ctx, text, ephemeral=True)


@marketplaces_group.register
class MarketplacesListCommand(
    lightbulb.SlashCommand, name="list", description="Show the marketplaces each alert in this channel checks.",
    hooks=read_hooks(),
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        alerts = await services.repository.list_alerts(channel_id=ctx.channel_id)
        if not alerts:
            await respond(ctx, "You have no alerts in this channel!")
            return
        sources = await services.repository.alert_sources([alert["id"] for alert in alerts])
        await services.respond_lines(ctx, [
            f"- {alert['search_query']} - {describe(sources[alert['id']], services.enabled_sources)}"
            for alert in alerts
        ])


@marketplaces_group.register
class MarketplacesOnCommand(
    lightbulb.SlashCommand, name="on", description="Check a marketplace for an alert in this channel.",
    hooks=management_hooks(),
):
    search_query = lightbulb.string(
        "search_query", "Alert in this channel.", autocomplete=search_query_autocomplete,
    )
    marketplace = lightbulb.string(
        "marketplace", "Marketplace to check; only its new listings are posted.", choices=MARKETPLACE_CHOICES,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        await change(ctx, services, self.search_query, self.marketplace, True)


@marketplaces_group.register
class MarketplacesOffCommand(
    lightbulb.SlashCommand, name="off", description="Stop checking a marketplace for an alert in this channel.",
    hooks=management_hooks(),
):
    search_query = lightbulb.string(
        "search_query", "Alert in this channel.", autocomplete=search_query_autocomplete,
    )
    marketplace = lightbulb.string("marketplace", "Marketplace to stop checking.", choices=MARKETPLACE_CHOICES)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, services: CommandServices):
        await change(ctx, services, self.search_query, self.marketplace, False)
