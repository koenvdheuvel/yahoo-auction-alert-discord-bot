from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from models import Alert, Item, Notification
from typing import Optional
from repositories import ItemRepository
import aiohttp
from logging import info, warning
from lightbulb import BotApp
from hikari import Embed, Color
from services.filter_service import FilterService
from services.filter_factory import FilterFactory
import asyncio
import hikari

@dataclass
class AbstractItem(ABC):
    id: str
    stock: int = 1
    price: int = 0
    buyout_price: int = 0
    title: str = ''
    image_url: str = ''
    message_id: int = 0
    end_time: datetime = None
    muted: bool = False

@dataclass
class StoredItem(AbstractItem):
    id: str
    stock: int = 0
    price: int = 0
    buyout_price: int = 0
    title: str = ''
    image_url: str = ''
    url: str = ''
    message_id: int = 0
    end_time: datetime = None
    muted: bool = False
    blacklisted: bool = False
        
class AlertChecker(ABC):
    def __init__(self, bot: BotApp, alert: Alert):
        self.bot = bot
        self.alert = alert
        self.search_query = alert.search_query
        self.channel_id = alert.channel_id
        self.item_repo = ItemRepository()
        self.up_to_date_counter = 0
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        }
        self.filter_factory = FilterFactory()
        self.filter_service = FilterService(filter_factory=self.filter_factory)

    def _is_bot_ready(self) -> bool:
        """Check if the bot and its REST client are ready for use."""
        try:
            # Check if bot exists and has a REST client
            if not self.bot or not hasattr(self.bot, 'rest'):
                return False
            
            # Check if REST client is active/available
            # This is a simple check - we could also check bot.is_alive if available
            return self.bot.rest is not None
        except Exception:
            return False

    @abstractmethod
    def get_embed_color(self) -> Color:
        pass

    @abstractmethod
    async def fetch_items(self, session: aiohttp.ClientSession) -> list:
        pass
    
    @abstractmethod
    async def normalize_item(self, data: dict) -> AbstractItem:
        """Factory method to create a new item instance from data."""
        pass

    async def find_stored_item(self, id: str) -> Optional[AbstractItem]:
        item = Item.select().where(Item.item_id == id).get_or_none()

        if item == None:
            return None
        
        return StoredItem(
            id=item.item_id,
            stock=item.stock,
            price=item.price,
            buyout_price=item.buyout_price,
            muted=item.muted,
            blacklisted=item.blacklisted(self.channel_id),
        )
    
    async def check_store(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                info(f"[{self.__class__.__name__}] Searching for {self.search_query}...")
                
                # Check for cancellation before fetching
                await asyncio.sleep(0)
                
                results = await self.fetch_items(session)
                if not results:
                    warning(f"[{self.__class__.__name__}] no search results found [{self.search_query}]")
                    return
        
                # Check for cancellation after fetching but before processing
                await asyncio.sleep(0)
                
                for i, result in enumerate(results):
                    # Check for cancellation more frequently during item processing
                    if i % 5 == 0:  # Every 5 items (increased from 10), yield control and check for cancellation
                        await asyncio.sleep(0)
                    
                    found_item = await self.normalize_item(result)
                    
                    # Check against filters before any other processing
                    if self.alert.filters: # Only check if alert has filters
                        filter_result = self.filter_service.check_item(found_item, self.alert)
                        if filter_result.is_filtered:
                            info(f"[{self.__class__.__name__}] Item filtered out: {found_item.title} by filters: {[f.id for f in filter_result.matched_filters]}")
                            continue # Skip this item

                    stored_item = await self.find_stored_item(found_item.id)
                    
                    if stored_item and stored_item.blacklisted:
                        info(f"[{self.__class__.__name__}] Item blacklisted: {found_item.title}")
                        continue

                    if stored_item:
                        await self.check_item(stored_item, found_item)
                    else:
                        await self.new_item(found_item)

                if self.up_to_date_counter > 0:
                    info(f"[{self.__class__.__name__}] {self.up_to_date_counter} items up to date [{self.search_query}]")
        
        except asyncio.CancelledError:
            info(f"[{self.__class__.__name__}] Check for '{self.search_query}' was cancelled")
            raise  # Re-raise CancelledError to ensure proper cancellation propagation
        except Exception as e:
            info(f"[{self.__class__.__name__}] Error during check for '{self.search_query}': {e}")
            raise

    async def check_item(self, stored_item: AbstractItem, found_item: AbstractItem) -> None:
        try:
            differences = []

            # Only alert and update  if the stock difference is greater than 1
            if stored_item.stock != found_item.stock and found_item.stock > 1:
                differences.append(f"Stock changed from {stored_item.stock} to {found_item.stock}")

            # Only alert and update if the price decrease is greater than 500 yen
            if int(stored_item.price)-int(found_item.price) > 500:
                differences.append(f"Price changed from {stored_item.price} to {found_item.price}")

            # Only alert and update if the buyout price difference is greater than 500 yen
            if abs(int(stored_item.buyout_price)-int(found_item.buyout_price)) > 500:
                differences.append(f"Buyout price changed from ¥{stored_item.buyout_price} to ¥{found_item.buyout_price}")

            if differences:
                await self.update_item(found_item, differences, stored_item.muted)
            
            # Yield control before database operation
            await asyncio.sleep(0)
            
            query = Item.update(
                item_id=found_item.id,
                checker=self.__class__.__name__,
                title=found_item.title,
                stock=found_item.stock,
                price=found_item.price,
                buyout_price=found_item.buyout_price,
                alert=self.alert,
            ).where(Item.item_id == found_item.id)
            query.execute()
            self.up_to_date_counter += 1
        except asyncio.CancelledError:
            info(f"[{self.__class__.__name__}] check_item cancelled for item {found_item.id}")
            raise
        
    async def update_item(self, item: AbstractItem, differences: list, muted: False) -> None:
        try:
            info(f"[{self.__class__.__name__}] Item updated: {item.title}")

            if not muted:
                message_id = await self.post_alert(item, differences)
                # Yield control before database operation
                await asyncio.sleep(0)
                query = Item.update(message_id=message_id).where(Item.item_id == item.id)
                query.execute()
        except asyncio.CancelledError:
            info(f"[{self.__class__.__name__}] update_item cancelled for item {item.id}")
            raise
            
    async def new_item(self, item: AbstractItem) -> None:
        try:
            info(f"[{self.__class__.__name__}] New item found: {item.title}")
            message_id = await self.post_alert(item, [])

            # Yield control before database operation
            await asyncio.sleep(0)
            
            query = Item.insert(
                item_id=item.id,
                checker=self.__class__.__name__,
                title=item.title,
                stock=item.stock,
                price=item.price,
                buyout_price=item.buyout_price,
                message_id=message_id,
                found_at=datetime.now(),
                updated_at=datetime.now(),
                alert=self.alert,
            )
            query.execute()
        except asyncio.CancelledError:
            info(f"[{self.__class__.__name__}] new_item cancelled for item {item.id}")
            raise

    def create_embed(self, item: AbstractItem) -> Embed:
        embed = Embed()
        embed.color = self.get_embed_color()
        embed.title = item.title
        embed.url = item.url
        embed.set_image(item.image_url)
        embed.add_field("Price", f"¥{item.price}", inline=True)
    
        if item.buyout_price > 0:
            embed.add_field("Buyout Price", f"¥{item.buyout_price}", inline=True)

        if item.stock > 1:
            embed.add_field("Stock", item.stock, inline=True)
        
        if item.end_time is not None:
            embed.add_field("End Time:", f"<t:{int(round(item.end_time.timestamp()))}:R>")

        embed.set_footer(f"Source: {self.__class__.__name__} — #{item.id} - {self.search_query}")
        return embed
    
    async def post_alert(self, item: AbstractItem, differences: list) -> int:
        try:
            embed = self.create_embed(item)
            if differences:
                embed.color = Color(0x00FF00) # Green
                for difference in differences:
                    embed.add_field("Update", difference, inline=False)

                # Send DM notifications for updates
                try:
                    db_item = Item.select().where(Item.item_id == item.id)
                    notifications = Notification.select().where(Notification.item == db_item)
                    for notification in notifications:
                        try:
                            user_id = notification.user_id
                            dm_channel = await self.bot.rest.create_dm_channel(user_id)
                            await self.bot.rest.create_message(dm_channel.id, embed=embed)
                        except Exception as dm_error:
                            warning(f"[{self.__class__.__name__}] Failed to send DM notification to user {user_id}: {dm_error}")
                            # Continue with other notifications even if one fails
                except Exception as notification_error:
                    warning(f"[{self.__class__.__name__}] Error processing notifications for item {item.id}: {notification_error}")

            # Send message to channel
            message = await self.bot.rest.create_message(self.channel_id, embed=embed)
            await message.add_reaction('🗑️')
            await message.add_reaction('🔔')

            return message.id
            
        except hikari.NotFoundError as e:
            warning(f"[{self.__class__.__name__}] Channel not found or accessible for item {item.title}: {e}")
            return 0
        except hikari.ForbiddenError as e:
            warning(f"[{self.__class__.__name__}] No permission to send message for item {item.title}: {e}")
            return 0
        except (hikari.RateLimitTooLongError) as e:
            warning(f"[{self.__class__.__name__}] Rate limit timed out while posting alert for item {item.title}: {e}")
            return 0
        except Exception as e:
            # This catches the "Cannot use an inactive REST client" error and others
            warning(f"[{self.__class__.__name__}] Failed to post alert for item {item.title}: {e}")
            return 0