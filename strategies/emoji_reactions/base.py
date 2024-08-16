# strategies/base_strategy.py
from abc import ABC, abstractmethod
import hikari

class EmojiActionStrategy(ABC):
    @abstractmethod
    async def execute(self, event: hikari.ReactionAddEvent, bot):
        pass
