from dataclasses import dataclass
import aiohttp
import json
from bs4 import BeautifulSoup
from logging import info
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
        url = f"https://zenmarket.jp/en/yahoo.aspx/getProducts?q={self.alert['name']}&sort=new&order=desc"
        async with session.post(url, json={"page": 1}, headers=self.headers) as response:
            response_json = await response.json()
            content = json.loads(response_json["d"])
            if content['Items']:
                return content['Items']
            return []

    async def normalize_item(self, data: dict) -> AbstractItem:
        price = 0
        buyout_price = 0

        if data["PriceTextControl"]:
            soup = BeautifulSoup(data.get('PriceTextControl'), 'lxml')
            price = soup.find("span", {"data-jpy": True}).get("data-jpy")
        
            if price:
                price = price[1:] # Remove the currency symbol
                price = int(price.replace(",", ""))
            
        if data["PriceBidOrBuyTextControl"]:
            soup = BeautifulSoup(data.get('PriceBidOrBuyTextControl'), 'lxml')
            buyout_price = soup.find("span", {"data-jpy": True}).get("data-jpy")

            if buyout_price:
                buyout_price = buyout_price[1:] # Remove the currency symbol
                buyout_price = int(buyout_price.replace(",", ""))

        return YahooAuctionItem(
            id=data.get('AuctionID'),
            image_url=data.get('Thumbnail'),
            title=data.get('Title', 'Unknown Title'),
            price=price,
            buyout_price=buyout_price
        )