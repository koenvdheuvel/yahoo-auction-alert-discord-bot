# strategies/delete_message_strategy.py
import hikari
from .base import EmojiActionStrategy
from logging import info
from models import Item, Notification

class RemoveNotificationStrategy(EmojiActionStrategy):
    async def execute(self, event: hikari.ReactionDeleteEvent, bot):
        channel_id = event.channel_id
        user_id = event.user_id
        message_id = event.message_id
        guild_id = event.guild_id

        message = await bot.rest.fetch_message(channel_id, message_id)
        dm_channel = await bot.rest.create_dm_channel(user_id)
        if message.author.id == bot.get_me().id:
            item = Item.select().where(Item.message_id == message_id).get()
            if item:
                notification = Notification.select().where(Notification.item == item, Notification.user_id == user_id).first()
                if notification:
                    notification.delete_instance()
                    await bot.rest.create_message(dm_channel.id, f"Notification removed for Item https://discord.com/channels/{guild_id}/{channel_id}/{message_id}.")
                    info(f"[{self.__class__.__name__}] Notification deleted for {item['name']} after reaction deletion by {event.user_id}.")