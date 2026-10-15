"""Reaction actions resolve only persisted item posts, including historical posts."""
from abc import ABC, abstractmethod
import logging

import hikari


logger = logging.getLogger(__name__)


class EmojiActionStrategy(ABC):
    @abstractmethod
    async def execute(self, event, bot):
        raise NotImplementedError

    async def lookup(self, event, bot):
        return await bot.services.repository.lookup_message(event.channel_id, event.message_id)

    async def confirm(self, event, bot, content):
        """The subscription is committed even when Discord disallows DMs."""
        try:
            channel = await bot.rest.create_dm_channel(event.user_id)
            await bot.rest.create_message(channel.id, content)
        except (hikari.ForbiddenError, hikari.NotFoundError):
            logger.warning("notification_confirmation_unavailable", exc_info=True,
                           extra={"fields": {"user_id": int(event.user_id),
                                              "channel_id": int(event.channel_id),
                                              "message_id": int(event.message_id)}})

    def message_url(self, event):
        guild_id = getattr(event, "guild_id", "@me")
        return f"https://discord.com/channels/{guild_id}/{event.channel_id}/{event.message_id}"
