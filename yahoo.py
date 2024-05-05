from dataclasses import dataclass
from datetime import datetime
import json
from logging import info
from hikari import Color
import math

import pytz

from storechecker import AlertChecker, AbstractItem

@dataclass
class YahooAuctionItem(AbstractItem):
    id: str
    stock: int = 1
    price: int = 0
    buyout_price: int = 0
    title: str = ''
    image_url: str = ''
    end_time: datetime = None

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
        
        content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/yahooauction/search?keyword={self.alert['name']}&sort=score&hits=20&page=1")
        if not content["items"]:
            return []
        
        page_count = math.ceil(content["count"] / 20)
        if page_count > 1:
            for page in range(2, page_count + 1):
                page_content = await fetch(f"https://www.fromjapan.co.jp/japan/sites/yahooauction/search?keyword={self.alert['name']}&sort=score&hits=20&page={page}")
                content["items"].extend(page_content["items"])

        return content["items"]

    async def normalize_item(self, data: dict) -> AbstractItem:
        auction_end_time = datetime.strptime(data.get('endTime'), '%Y/%m/%d %H:%M:%S')
        japan_timezone = pytz.timezone('Asia/Tokyo')
        end_time_utc = japan_timezone.localize(auction_end_time).astimezone(pytz.utc)

        return YahooAuctionItem(
            id=data.get('id'),
            stock=int(data.get('stock')),
            image_url=data.get('imageUrl'),
            end_time=end_time_utc,
            title=data.get('title', 'Unknown Title'),
            price=int(data.get('price')),
            buyout_price=int(data.get('buyItNowPrice'))
        )