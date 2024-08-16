# strategies/delete_message_strategy.py
import hikari
from .base import EmojiActionStrategy
from logging import info
from models import Item, Notification

class SetupNotificationStrategy(EmojiActionStrategy):
    async def execute(self, event: hikari.ReactionAddEvent, bot):
        channel_id = event.channel_id
        message_id = event.message_id
        guild_id = event.guild_id

        message = await bot.rest.fetch_message(channel_id, message_id)
        dm_channel = await bot.rest.create_dm_channel(event.user_id)
        if message.author.id == bot.get_me().id:
            item = Item.select().where(Item.message_id == message_id).get()
            if item:
                Notification.create(item=item, user_id=event.user_id)
                
                await bot.rest.create_message(dm_channel.id, f"Notification set for Item https://discord.com/channels/{guild_id}/{channel_id}/{message_id}.")
                info(f"[{self.__class__.__name__}] Notification set for {item.item_id} after reaction by {event.user_id}.")
            