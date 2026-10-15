import logging
from .base import EmojiActionStrategy


logger = logging.getLogger(__name__)


class RemoveNotificationStrategy(EmojiActionStrategy):
    async def execute(self, event, bot):
        message = await self.lookup(event, bot)
        if message is None:
            return
        removed = await bot.services.repository.unsubscribe(message["item_id"], event.user_id)
        if not removed:
            return
        logger.info("notification_unsubscribed",
                    extra={"fields": {"source": message["source"],
                                      "external_id": message["external_id"],
                                      "user_id": int(event.user_id),
                                      "channel_id": int(event.channel_id)}})
        await self.confirm(event, bot, f"Notification removed for item {self.message_url(event)}.")
