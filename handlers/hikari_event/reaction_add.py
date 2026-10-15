import hikari
from .base import EventHandler
from strategies.emoji_reactions.delete_message import DeleteMessageStrategy
from strategies.emoji_reactions.setup_notification import SetupNotificationStrategy


class ReactionAddHandler(EventHandler):
    def __init__(self):
        self.emoji_strategies = {
            "🗑️": DeleteMessageStrategy(),
            "🔔": SetupNotificationStrategy(),
        }

    async def handle(self, event: hikari.ReactionAddEvent, bot) -> None:
        bot_user = bot.get_me()
        if bot_user is None or event.user_id == bot_user.id:
            return
        if getattr(getattr(event, "member", None), "is_bot", False):
            return
        strategy = self.emoji_strategies.get(event.emoji_name)
        if strategy:
            await strategy.execute(event, bot)
