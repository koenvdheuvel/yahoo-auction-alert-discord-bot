import logging

import hikari
from handlers.hikari_event.reaction_add import ReactionAddHandler
from handlers.hikari_event.reaction_delete import ReactionDeleteHandler


logger = logging.getLogger(__name__)


class HikariEventProcessor:
    def __init__(self):
        self._handlers = {
            hikari.GuildReactionAddEvent: ReactionAddHandler(),
            hikari.GuildReactionDeleteEvent: ReactionDeleteHandler(),
        }

    async def process_event(self, event: hikari.Event, bot):
        handler = self._handlers.get(type(event))
        if handler is None:
            return
        try:
            await handler.handle(event, bot)
        except Exception:
            runtime = getattr(bot.services, "runtime", None)
            if runtime is not None:
                runtime.metrics.reaction_errors.inc()
            logger.exception("reaction_handler_failed",
                             extra={"fields": {"channel_id": int(event.channel_id),
                                                "message_id": int(event.message_id),
                                                "user_id": int(event.user_id),
                                                "emoji": event.emoji_name}})
