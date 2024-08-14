from peewee import DoesNotExist
from typing import Optional
from models import Item, Blacklist

class ItemRepository():
    def find_by_id(item_id: str) -> Optional[Item]:
        try:
            return Item.get(Item.item_id == item_id)
        except Item.DoesNotExist:
            return None