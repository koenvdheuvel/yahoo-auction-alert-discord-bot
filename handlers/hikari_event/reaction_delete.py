import hikari
from .base import EventHandler
from strategies.emoji_reactions.remove_notification import RemoveNotificationStrategy


class ReactionDeleteHandler(EventHandler):
    def __init__(self):
        self.emoji_strategies = {"🔔": RemoveNotificationStrategy()}

    async def handle(self, event: hikari.ReactionDeleteEvent, bot) -> None:
        bot_user = bot.get_me()
        if bot_user is None or event.user_id == bot_user.id:
            return
        strategy = self.emoji_strategies.get(event.emoji_name)
        if strategy:
            await strategy.execute(event, bot)
