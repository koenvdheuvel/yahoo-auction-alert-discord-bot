import os
import dotenv
import lightbulb
import hikari
import dataset
import asyncio
import importlib
import sys
from models import create_tables, Alert, Blacklist, Notification, Item
from logging import info
from yahoo import YahooAuctionsChecker
from mercari import MercariChecker
from surugaya import SurugayaChecker
from processors.hikari_event import HikariEventProcessor
from commands.base import BaseCommand

# Temporarily disabled for debugging purposes
# if os.name != "nt":
#     import uvloop
#     asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

dotenv.load_dotenv()

db = dataset.connect("sqlite:///alerts.db")
bot = lightbulb.BotApp(os.environ["BOT_TOKEN"])
bot.d.table = db["alerts"]
bot.d.blacklist = db["blacklist"]
bot.d.synced = db["synced_alerts"]
bot.d.notifications = db["notifications"]

async def create_check_tasks(alerts: list):
    tasks = []
    checkers = {
        "ENABLE_YAHOO_AUCTION": YahooAuctionsChecker,
        "ENABLE_MERCARI": MercariChecker,
        "ENABLE_SURUGAYA": SurugayaChecker
    }

    for alert in alerts:
        # change to != for debugging purposes
        if alert.search_query == 'BABYMETAL BEGINS':
            continue
        info(f"Checking alert: {alert.search_query}")
        for env_var, CheckerClass in checkers.items():
            if os.getenv(env_var, "true") == "true":
                checker = CheckerClass(bot, alert)
                task = asyncio.create_task(bound_check(semaphore, checker.check_store))
                tasks.append(task)

    return tasks

async def check_alerts(input_alerts=None) -> None:
    while True:
        alerts = input_alerts if input_alerts else Alert.select()
        tasks = await create_check_tasks(alerts)

        if tasks:
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                info(f"Error during task execution: {e}")
        else:
            print("No tasks to run")

        info(f"Done checking alerts. Sleeping for {os.getenv('CHECK_INTERVAL', '60')} seconds...")
        await asyncio.sleep(int(os.getenv("CHECK_INTERVAL", "60")))

semaphore = asyncio.Semaphore(4)
async def bound_check(semaphore, func, *args):
    async with semaphore:
        return await func(*args)

def load_commands(bot):
    # Assuming command classes are in the 'commands' directory
    command_dir = "commands"
    sys.path.append(command_dir)

    for module_name in os.listdir(command_dir):
        if module_name.endswith(".py"):
            module_name = module_name[:-3]
            module = importlib.import_module(module_name)
            # Dynamically instantiate the command class and pass the bot
            for attr in dir(module):
                cls = getattr(module, attr)
                if isinstance(cls, type) and issubclass(cls, BaseCommand) and cls is not BaseCommand:
                    cls(bot)

@bot.listen()
async def on_ready(event: hikari.StartingEvent) -> None:
    info("Starting event loop...")
    asyncio.create_task(check_alerts())
    create_tables()
        
processor = HikariEventProcessor()
@bot.listen(hikari.Event)
async def on_event(event: hikari.Event):
    await processor.process_event(event, bot)

if __name__ == "__main__":
    load_commands(bot)
    bot.run(
        propagate_interrupts=True,      # Any OS interrupts get rethrown as errors.
        coroutine_tracking_depth=30,
        asyncio_debug=True,
        activity=hikari.Activity(
            name="Posters", type=hikari.ActivityType.WATCHING
        )
    )
