from abc import ABC, abstractmethod


class ItemFilter(ABC):
    @abstractmethod
    def match(self, item) -> bool:
        raise NotImplementedError
