import hikari
import hikari.events.reaction_events
from handlers.hikari_event.reaction_add import ReactionAddHandler
from handlers.hikari_event.reaction_delete import ReactionDeleteHandler

class HikariEventProcessor:
    def __init__(self):
        self._handlers = {
            hikari.events.reaction_events.GuildReactionAddEvent: ReactionAddHandler(),
            hikari.events.reaction_events.GuildReactionDeleteEvent: ReactionDeleteHandler(),
        }

    async def process_event(self, event: hikari.Event, bot):
        handler = self._handlers.get(type(event))
        if handler:
            await handler.handle(event, bot)
        # else:
            # print(f"Unhandled event: {type(event)}")