import logging

import hikari
from .base import EmojiActionStrategy


logger = logging.getLogger(__name__)


class DeleteMessageStrategy(EmojiActionStrategy):
    async def execute(self, event, bot):
        message = await self.lookup(event, bot)
        if message is None:
            return
        await bot.services.repository.blacklist_item(message["item_id"], event.channel_id)
        try:
            await bot.rest.delete_message(event.channel_id, event.message_id)
        except hikari.NotFoundError:
            # Another reaction or cleanup may already have removed the same post.
            pass
        except hikari.ForbiddenError:
            logger.warning("blacklisted_message_delete_forbidden", exc_info=True,
                           extra={"fields": {"channel_id": int(event.channel_id),
                                              "message_id": int(event.message_id)}})
            return
        await bot.services.repository.mark_message_deleted(event.channel_id, event.message_id)
        logger.info("item_blacklisted",
                    extra={"fields": {"source": message["source"],
                                      "external_id": message["external_id"],
                                      "channel_id": int(event.channel_id),
                                      "message_id": int(event.message_id)}})
