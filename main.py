import os
import dotenv
import lightbulb
import hikari
import asyncio
import importlib
import sys
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from models import create_tables, Alert
from logging import info
from yahoo import YahooAuctionsChecker
from mercari import MercariChecker
from surugaya import SurugayaChecker
from processors.hikari_event import HikariEventProcessor
from commands.base import BaseCommand
from logging_handler import setup_discord_logging
from task_manager import setup_task_manager, get_task_manager

# Temporarily disabled for debugging purposes
# if os.name != "nt":
#     import uvloop
#     asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

dotenv.load_dotenv()

bot = lightbulb.BotApp(
    os.environ["BOT_TOKEN"],
    #logs="DEBUG",
)

# Configure APScheduler
scheduler = AsyncIOScheduler()

# Centralized Checkers Configuration
CHECKERS_CONFIG = {
    "ENABLE_YAHOO_AUCTION": YahooAuctionsChecker,
    "ENABLE_MERCARI": MercariChecker,
    "ENABLE_SURUGAYA": SurugayaChecker
}

semaphore = asyncio.Semaphore(4)

async def bound_check(semaphore_obj, func, *args):
    async with semaphore_obj:
        return await func(*args)

def get_checkers(alert_instance: Alert):
    """Yields checker instances for a given alert based on environment flags."""
    for env_var, CheckerClass in CHECKERS_CONFIG.items():
        if os.getenv(env_var, "true").lower() == "true":
            yield CheckerClass(bot, alert_instance)

async def perform_single_alert_check(alert_id: int) -> None:
    """
    Fetches an alert by its ID and runs all enabled checks for it.
    Now simplified - task tracking is handled by TaskManager.
    """
    # Check if bot is ready before starting any checks
    if not bot or not hasattr(bot, 'rest') or bot.rest is None:
        info(f"Check: Bot REST client not available, skipping alert check for ID {alert_id}")
        return
    
    try:
        alert = Alert.get_by_id(alert_id)
        if not alert:
            info(f"Check: Alert with ID {alert_id} not found.")
            return
    except Exception as e:
        info(f"Error fetching alert {alert_id} for check: {e}")
        return

    if alert.search_query == 'BABYMETAL BEGINS': # TODO: Remove this condition
        info(f"Skipping check for development: {alert.search_query}")
        return

    info(f"Starting checks for alert: '{alert.search_query}' (ID: {alert.id})")
    
    current_checker_tasks = []
    try:
        for checker_instance in get_checkers(alert):
            task = asyncio.create_task(bound_check(semaphore, checker_instance.check_store), name=f"CheckerTask_AlertID_{alert_id}_{checker_instance.__class__.__name__}")
            current_checker_tasks.append(task)

        if not current_checker_tasks:
            info(f"No checkers enabled for alert: '{alert.search_query}' (ID: {alert.id})")
            return

        info(f"Executing {len(current_checker_tasks)} checker tasks for alert ID {alert_id}: {[t.get_name() for t in current_checker_tasks]}")

        await asyncio.gather(*current_checker_tasks)
        info(f"Successfully completed checks for alert: '{alert.search_query}' (ID: {alert.id})")
        
    except asyncio.CancelledError:
        info(f"CANCELLATION: Main task for alert '{alert.search_query}' (ID: {alert.id}) was cancelled. Immediately cancelling {len(current_checker_tasks)} individual checker tasks...")
        
        # Cancel all individual checker tasks IMMEDIATELY
        cancelled_count = 0
        for task in current_checker_tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1
                info(f"CANCELLATION: Cancelled checker task: {task.get_name()}")
        
        info(f"CANCELLATION: Requested cancellation for {cancelled_count} checker tasks, waiting for them to stop...")
        
        # Wait more aggressively for cancellations to take effect
        if cancelled_count > 0:
            try:
                # Use wait instead of gather to handle cancellations better
                done, pending = await asyncio.wait(current_checker_tasks, timeout=3.0, return_when=asyncio.ALL_COMPLETED)
                
                if pending:
                    info(f"CANCELLATION WARNING: {len(pending)} checker tasks did not complete within timeout. Force-cancelling...")
                    for task in pending:
                        task.cancel()
                        info(f"CANCELLATION: Force-cancelled: {task.get_name()}")
                    
                    # Wait one more time for force-cancelled tasks
                    try:
                        await asyncio.wait(pending, timeout=1.0)
                    except asyncio.TimeoutError:
                        info(f"CANCELLATION ERROR: Some tasks still pending after force cancellation")
                else:
                    info(f"CANCELLATION: All {len(done)} checker tasks stopped successfully")
                    
            except Exception as e:
                info(f"CANCELLATION ERROR: Exception during checker task cancellation for alert ID {alert_id}: {e}")
        
        info(f"CANCELLATION COMPLETE: Alert check cancellation finished for '{alert.search_query}' (ID: {alert.id})")
        raise  # Re-raise so TaskManager can handle it
        
    except Exception as e:
        info(f"ERROR: Exception during checks for alert '{alert.search_query}' (ID: {alert.id}): {e}")
        
        # If there's an error, also cancel any remaining tasks to prevent orphaned checkers
        info(f"ERROR CLEANUP: Cancelling {len(current_checker_tasks)} checker tasks due to error...")
        for task in current_checker_tasks:
            if not task.done():
                task.cancel()
                info(f"ERROR CLEANUP: Cancelled: {task.get_name()}")
        
        raise  # Re-raise so TaskManager can handle it

async def schedule_all_active_alerts_job() -> None:
    """Schedule all active alerts using the task manager."""
    task_manager = get_task_manager()
    
    try:
        alerts = Alert.select()
        if not alerts:
            return

        scheduled_count = 0
        skipped_count = 0
        for alert_item in alerts:
            try:
                task_id = task_manager.schedule_alert_check(alert_item.id, alert_item.search_query)
                if task_id is not None:
                    scheduled_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                info(f"Failed to schedule alert ID {alert_item.id}: {e}")

        if scheduled_count > 0 or skipped_count > 0:
            info(f"Scheduler: Scheduled {scheduled_count} new alert(s), skipped {skipped_count} duplicate(s)")

    except Exception as e:
        info(f"Error during scheduling cycle: {e}")

def load_commands(bot_app: lightbulb.BotApp):
    command_dir = "commands"
    if command_dir not in sys.path and os.path.abspath(command_dir) not in sys.path:
        sys.path.append(os.path.abspath(command_dir))

    for module_filename in os.listdir(command_dir):
        if module_filename.endswith(".py") and module_filename != "__init__.py":
            module_name_to_import = module_filename[:-3]
            try:
                module = importlib.import_module(module_name_to_import)
                importlib.reload(module) 
                for attr_name in dir(module):
                    cls_obj = getattr(module, attr_name)
                    if isinstance(cls_obj, type) and issubclass(cls_obj, BaseCommand) and cls_obj is not BaseCommand:
                        info(f"Loading command module: {module_name_to_import} -> class {attr_name}")
                        cls_obj(bot_app)
            except ImportError as e:
                info(f"Error importing command module {module_name_to_import}: {e}")
            except Exception as e:
                info(f"Error loading class from {module_name_to_import}: {e}")

@bot.listen()
async def on_ready(event: hikari.StartingEvent) -> None:
    info("Bot is starting...")
    info("Initializing database tables...")
    create_tables()
    
    info("Setting up Discord logging handler...")
    setup_discord_logging(bot)
    
    info("Loading commands...")
    load_commands(bot) 

    info("Starting APScheduler...")
    scheduler.start()
    
    info("Setting up task manager...")
    setup_task_manager(scheduler, perform_single_alert_check)
    
    info(f"Scheduling recurring alert checks every {os.getenv('CHECK_INTERVAL', '60')} seconds.")
    scheduler.add_job(
        schedule_all_active_alerts_job,
        'interval',
        seconds=int(os.getenv("CHECK_INTERVAL", "60")),
        id="recurring_alert_scheduler",
        replace_existing=True,
        misfire_grace_time=300 
    )
    
    # Wait a moment for the bot to be fully ready before scheduling initial checks
    info("Waiting for bot to be fully ready...")
    await asyncio.sleep(3)
    
    info("Performing initial scheduling of all active alerts...")
    await schedule_all_active_alerts_job()
    
    info("Bot is ready and scheduler is running.")
    info("💡 Use /enablelogs in a Discord channel to start receiving logs there!")
    info("💡 Use /taskstatus to see scheduled, running, and completed tasks!")
      
processor = HikariEventProcessor()
@bot.listen(hikari.Event)
async def on_event(event_obj: hikari.Event):
    await processor.process_event(event_obj, bot)

if __name__ == "__main__":
    bot.run(
        propagate_interrupts=True,
        coroutine_tracking_depth=30,
        asyncio_debug=False,
        activity=hikari.Activity(
            name="Posters", type=hikari.ActivityType.WATCHING
        )
    )
