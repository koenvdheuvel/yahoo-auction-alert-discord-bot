from dataclasses import dataclass
import aiohttp
import json 
import math
from bs4 import BeautifulSoup
from logging import info, error
from hikari import Color

from storechecker import AlertChecker, AbstractItem

@dataclass
class YahooAuctionItem(AbstractItem):
    id: str
    stock: int = 1
    price: int = 0
    buyout_price: int = 0
    title: str = ''
    image_url: str = ''
    
    @property
    def url(self) -> str:
        return f"https://buyee.jp/item/yahoo/auction/{self.id}"

class YahooAuctionsChecker(AlertChecker):
    def get_embed_color(self) -> Color:
        return Color(0xFFA500) # Orange

    async def fetch_items(self, session) -> list:
        async def fetch(url):
            async with session.get(url, headers=self.headers) as response:
                return await response.json()

        items_per_page = 99
        content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/yahooauction/search?keyword={self.search_query}&sort=score&hits={items_per_page}&page=1")
        
        if 'items' not in content:
            error(f"Failed to fetch items for {self.search_query}")
            error(content)

        if not content.get("items"):
            return []
        
        page_count = math.ceil(content["count"] / items_per_page)
        if page_count > 1:
            for page in range(2, page_count + 1):
                page_content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/yahooauction/search?keyword={self.search_query}&sort=score&hits={items_per_page}&page={page}")
                content["items"].extend(page_content["items"])

        return content["items"]

    async def normalize_item(self, data: dict) -> AbstractItem:
        return YahooAuctionItem(
            id=data.get('id'),
            image_url=data.get('imageUrl'),
            title=data.get('title', 'Unknown Title'),
            price=data.get('price'),
            buyout_price=data.get('buyItNowPrice'),
        )