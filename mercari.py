from dataclasses import dataclass
from logging import error
from hikari import Color
import math
from storechecker import AlertChecker, AbstractItem

@dataclass
class MercariItem(AbstractItem):
    id: str
    stock: int = 0
    price: int = 0
    title: str = ''
    image_url: str = ''
    
    @property
    def url(self) -> str:
        return f"https://jp.mercari.com/item/{self.id}"

class MercariChecker(AlertChecker):
    def get_embed_color(self) -> Color:
        return Color(0xFF0000) # Red
    
    async def fetch_items(self, session) -> list:
        async def fetch(url):
            async with session.get(url, headers=self.headers) as response:
                return await response.json()
        
        content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/mercari/search?keyword={self.search_query}&sort=score&hits=24&page=1")
        if 'items' not in content:
            error(f"Failed to fetch items for {self.search_query}")
            error(content)
        
        if not content.get("items"):
            return []

        page_count = math.ceil(content["count"] / 24)
        if page_count > 1:
            for page in range(2, page_count + 1):
                page_content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/mercari/search?keyword={self.search_query}&sort=score&hits=24&page={page}")
                content["items"].extend(page_content["items"])

        return content["items"]

    async def normalize_item(self, data: dict) -> AbstractItem:
        return MercariItem(
            id=data.get('id'),
            stock=int(data.get('stock')),
            price=int(data.get('price')),
            title=data.get('title', 'Unknown Title'),
            image_url=data.get('imageUrl')
        )