from dataclasses import dataclass
import math
import aiohttp
from bs4 import BeautifulSoup
from logging import info, warning
from hikari import Color
from storechecker import AlertChecker, AbstractItem

@dataclass
class SurugayaItem(AbstractItem):
    id: str
    stock: int = 0
    price: int = 0
    title: str = ''
    image_url: str = ''

    @property
    def url(self) -> str:
        return f"https://www.suruga-ya.jp/product/detail/{self.id}"

class SurugayaChecker(AlertChecker):
    def get_embed_color(self) -> Color:
        return Color(0x0000FF) # Blue
    
    async def fetch_items(self, session) -> list:
        async def fetch(url):
            async with session.get(url, headers=self.headers) as response:
                return await response.json()
        
        content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/surugaya/search?keyword={self.alert['name']}&sort=score&hits=24&page=1")
        
        if 'items' not in content:
            warning(f"Failed to fetch items for {self.alert['name']}")
            warning(content)

        if not content.get("items"):
            return []
        
        page_count = math.ceil(content["count"] / 24)
        if page_count > 1:
            for page in range(2, page_count + 1):
                page_content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/surugaya/search?keyword={self.alert['name']}&sort=score&hits=24&page={page}")
                content["items"].extend(page_content["items"])

        return content["items"]

    async def normalize_item(self, data: dict) -> AbstractItem:
        item = SurugayaItem(
            id=data.get('id'),
            stock=data.get('stock'),
            price=data.get('price'),
            title=data.get('title'),
            image_url=data.get('imageUrl')
        )

        async with aiohttp.ClientSession() as session:
            page_response = await session.get(item.url, headers=self.headers)
            soup = BeautifulSoup(await page_response.text(), 'html.parser')
            item.title = soup.find('h1', id="item_title").text

        return item