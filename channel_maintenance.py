"""Channel upkeep shared by the slash commands and the dashboard.

Both look at the channel's latest HISTORY_SCAN_LIMIT messages: /cleanup deletes the bot's posts
there, and /reacttocleanup adds the 🗑️ reaction to the tracked listing posts among them.
"""
from dataclasses import dataclass

import hikari


# This module does not import the commands package: the commands import it.
HISTORY_SCAN_LIMIT = 1000
MAX_DELETE_COUNT = 100


def is_bot_post(message, bot_id):
    """The bot's own posts, without its answers to commands."""
    return (
        message.author.id == bot_id
        and getattr(message, "type", hikari.MessageType.DEFAULT)
        not in (hikari.MessageType.CHAT_INPUT, hikari.MessageType.CONTEXT_MENU_COMMAND)
        and not getattr(message, "interaction_metadata", None)
    )


@dataclass
class Progress:
    """How far a run got. It is updated as the run goes, so a failure part way still says how many."""
    done: int = 0


async def delete_recent_bot_posts(rest, repository, bot_id, channel_id, count, progress=None):
    """Delete up to count of the bot's posts among the channel's latest messages.

    Command responses are left alone. Returns how many posts were deleted. Raises
    hikari.ForbiddenError when the bot may not read the history or delete.
    """
    if not 1 <= count <= MAX_DELETE_COUNT:
        raise ValueError(f"Count must be between 1 and {MAX_DELETE_COUNT}.")
    progress = progress or Progress()
    async for message in rest.fetch_messages(channel_id).limit(HISTORY_SCAN_LIMIT):
        if not is_bot_post(message, bot_id):
            continue
        try:
            await rest.delete_message(channel_id, message.id)
        except hikari.NotFoundError:
            await repository.mark_message_deleted(channel_id, message.id)
            continue
        await repository.mark_message_deleted(channel_id, message.id)
        progress.done += 1
        if progress.done >= count:
            break
    return progress.done


async def add_cleanup_reactions(rest, repository, bot_id, channel_id, progress=None):
    """Add the 🗑️ reaction to the tracked listing posts among the channel's latest messages.

    Returns how many reactions were added. Raises hikari.ForbiddenError when the bot may not
    read the history or add reactions.
    """
    progress = progress or Progress()
    async for message in rest.fetch_messages(channel_id).limit(HISTORY_SCAN_LIMIT):
        if not is_bot_post(message, bot_id):
            continue
        if await repository.lookup_message(channel_id, message.id) is None:
            continue
        try:
            await rest.add_reaction(channel_id, message.id, "🗑️")
        except hikari.NotFoundError:
            await repository.mark_message_deleted(channel_id, message.id)
            continue
        progress.done += 1
    return progress.done
