# strategies/delete_message_strategy.py
import hikari
from .base import EmojiActionStrategy
from logging import info
from models import Blacklist, Item

class DeleteMessageStrategy(EmojiActionStrategy):
    async def execute(self, event: hikari.ReactionAddEvent, bot):
        channel_id = event.channel_id
        message_id = event.message_id

        message = await bot.rest.fetch_message(channel_id, message_id)
        if message.author.id == bot.get_me().id:
            item = Item.select().where(Item.message_id == message_id).get()
            if item:
                Blacklist.create(item=item, channel_id=channel_id)
                info(f"[{self.__class__.__name__}] Blacklisted item {item.item_id} after reaction by {event.user_id}.")

            await bot.rest.delete_message(channel_id, message_id)
            info(f"[{self.__class__.__name__}] Message {message_id} deleted after reaction.")
