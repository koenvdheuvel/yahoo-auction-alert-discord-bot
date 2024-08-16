from abc import ABC, abstractmethod
import hikari

class EventHandler(ABC):
    @abstractmethod
    async def handle(self, event: hikari.Event, bot) -> None:
        pass