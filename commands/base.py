"""Native Lightbulb 3 services, execution hooks and bounded Discord responses."""
import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

import hikari
import lightbulb


ADMIN_PERMISSION = hikari.Permissions.MANAGE_CHANNELS
GUILD_CONTEXTS = [hikari.ApplicationContextType.GUILD]
GUILD_INSTALLS = [hikari.ApplicationIntegrationType.GUILD_INSTALL]
# The longest search query /register takes. Discord enforces it on the option; the dashboard
# checks it with clean_search_query.
SEARCH_QUERY_MAX_LENGTH = 100
PAGINATION_TIMEOUT = 120
NO_MENTIONS = {"mentions_everyone": False, "user_mentions": False, "role_mentions": False}
logger = logging.getLogger(__name__)


class GuildOnlyError(Exception):
    """The command requires a guild interaction."""


@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS, skip_when_failed=True)
def guild_only(_, ctx: lightbulb.Context):
    if ctx.guild_id is None:
        raise GuildOnlyError("This command can only be used in a server.")


@lightbulb.hook(lightbulb.ExecutionSteps.PRE_INVOKE, skip_when_failed=True)
async def defer_public(_, ctx: lightbulb.Context):
    await ctx.defer()


@lightbulb.hook(lightbulb.ExecutionSteps.PRE_INVOKE, skip_when_failed=True)
async def defer_private(_, ctx: lightbulb.Context):
    await ctx.defer(ephemeral=True)


def management_hooks():
    return [guild_only, lightbulb.prefab.has_permissions(ADMIN_PERMISSION), defer_private]


def read_hooks():
    return [guild_only, defer_public]


def clean_search_query(value):
    """A new search query as /register takes it: 1 to SEARCH_QUERY_MAX_LENGTH characters, then
    without surrounding spaces, and not empty. Raises ValueError with what to fix."""
    if not isinstance(value, str) or not 1 <= len(value) <= SEARCH_QUERY_MAX_LENGTH:
        raise ValueError(f"Enter a search query of 1 to {SEARCH_QUERY_MAX_LENGTH} characters.")
    value = value.strip()
    if not value:
        raise ValueError("Enter a non-empty search query.")
    return value


async def respond(ctx, content, *, ephemeral=False, **kwargs):
    return await ctx.respond(content, ephemeral=ephemeral, **NO_MENTIONS, **kwargs)


def paginate_lines(lines, max_chars=1800):
    pages, current = [], ""
    for line in lines:
        line = line.replace("@", "@\u200b")
        for start in range(0, max(1, len(line)), max_chars):
            part = line[start:start + max_chars]
            if current and len(current) + len(part) + 1 > max_chars:
                pages.append(current)
                current = ""
            current = current + "\n" + part if current else part
    if current or not pages:
        pages.append(current or "None")
    return pages


class PageMenu(lightbulb.components.Menu):
    """A finite native component menu restricted to the invoking user."""
    def __init__(self, pages, owner_id):
        self.pages, self.owner_id, self.index = pages, owner_id, 0
        self.previous = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self.previous_page, label="Previous", disabled=True,
        )
        self.next = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self.next_page, label="Next", disabled=len(pages) < 2,
        )

    @property
    def content(self):
        return f"{self.pages[self.index]}\n\nPage {self.index + 1}/{len(self.pages)}"

    async def predicate(self, ctx):
        if ctx.user.id == self.owner_id:
            return True
        await respond(ctx, "Only the person who opened this list can change its page.", ephemeral=True)
        return False

    async def previous_page(self, ctx):
        await self.show_page(ctx, self.index - 1)

    async def next_page(self, ctx):
        await self.show_page(ctx, self.index + 1)

    async def show_page(self, ctx, index):
        self.index = min(max(index, 0), len(self.pages) - 1)
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index == len(self.pages) - 1
        await ctx.respond(self.content, edit=True, rebuild_menu=True, **NO_MENTIONS)


@dataclass
class CommandServices:
    bot: hikari.GatewayBot
    repository: Any
    pagination_tasks: set = field(default_factory=set)

    async def respond_lines(self, ctx, lines, *, ephemeral=False):
        pages = paginate_lines(lines)
        if len(pages) == 1:
            await respond(ctx, pages[0], ephemeral=ephemeral)
            return
        menu = PageMenu(pages, ctx.user.id)
        response_id = await respond(ctx, menu.content, ephemeral=ephemeral, components=menu)
        task = asyncio.create_task(self._run_menu(ctx, menu, response_id),
                                   name="auction-bot:command-pagination")
        self.pagination_tasks.add(task)
        task.add_done_callback(self._pagination_done)

    def _pagination_done(self, task):
        self.pagination_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("pagination_failed", exc_info=(type(error), error, error.__traceback__))

    async def _run_menu(self, ctx, menu, response_id):
        try:
            await menu.attach(ctx.client, timeout=PAGINATION_TIMEOUT)
        except TimeoutError:
            pass
        finally:
            menu.disable_all_components()
            try:
                await ctx.edit_response(response_id, components=menu)
            except (hikari.NotFoundError, hikari.ForbiddenError):
                logger.debug("pagination_response_unavailable", exc_info=True)

    async def close(self):
        tasks = list(self.pagination_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.pagination_tasks.clear()


@lightbulb.di.with_di
async def search_query_autocomplete(ctx: lightbulb.AutocompleteContext, services: CommandServices):
    alerts = await services.repository.list_alerts(channel_id=ctx.interaction.channel_id)
    search = str(ctx.focused.value or "").casefold()
    choices = [
        alert["search_query"] for alert in alerts
        if search in alert["search_query"].casefold() and len(alert["search_query"]) <= 100
    ][:25]
    await ctx.respond(choices)


def log_change(event, ctx, **fields):
    logger.info(event, extra={"fields": {
        "channel_id": int(ctx.channel_id), "guild_id": int(ctx.guild_id),
        "actor_id": int(ctx.user.id), **fields,
    }})
