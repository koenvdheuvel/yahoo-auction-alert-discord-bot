# handlers/reaction_add_handler.py
import hikari
from .base import EventHandler
from strategies.emoji_reactions.delete_message import DeleteMessageStrategy
from strategies.emoji_reactions.setup_notification import SetupNotificationStrategy
from logging import info
# Import other strategies as needed

class ReactionAddHandler(EventHandler):
    def __init__(self):
        self.emoji_strategies = {
            '🗑️': DeleteMessageStrategy(),
            '🔔': SetupNotificationStrategy(),
            # Add more emoji to strategy mappings here
        }

    async def handle(self, event: hikari.ReactionAddEvent, bot) -> None:
        if event.user_id == bot.get_me().id:
            return  # Ignore reactions added by the bot
        info(f"[{self.__class__.__name__}] Reaction {event.emoji_name} by {event.user_id} on message {event.message_id}")
        strategy = self.emoji_strategies.get(event.emoji_name)
        if strategy:
            await strategy.execute(event, bot)
