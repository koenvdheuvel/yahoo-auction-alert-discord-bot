import os
import dotenv
import lightbulb
import hikari
import dataset
import asyncio
from logging import info
from yahoo import YahooAuctionsChecker
from mercari import MercariChecker
from surugaya import SurugayaChecker
import os

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

async def check_alerts(input_alerts=None) -> None:
    while True:
        if input_alerts:
            alerts = input_alerts
        else:
            alerts = list(bot.d.table.all())

        tasks = []
        for alert in alerts:
            if os.getenv("ENABLE_YAHOO_AUCTION", "true") == "true":
                yahoo_checker = YahooAuctionsChecker(bot, alert)
                task = asyncio.create_task(bound_check(semaphore, yahoo_checker.check_store))
                tasks.append(task)

            if os.getenv("ENABLE_MERCARI", "true") == "true":
                mercari_checker = MercariChecker(bot, alert)
                task = asyncio.create_task(bound_check(semaphore, mercari_checker.check_store))
                tasks.append(task)
         
            if os.getenv("ENABLE_SURUGAYA", "true") == "true":
                surugaya_checker = SurugayaChecker(bot, alert)
                task = asyncio.create_task(bound_check(semaphore, surugaya_checker.check_store))
                tasks.append(task)

        if tasks:
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                info(f"Error during task execution: {e}")
        else:
            print("No tasks to run")

        info(f"Done checking alerts. Sleeping for {os.getenv('CHECK_INTERVAL', '60')} seconds...")
        await asyncio.sleep(int(os.getenv("CHECK_INTERVAL", "60")))

semaphore = asyncio.Semaphore(3)
async def bound_check(semaphore, func, *args):
    async with semaphore:
        return await func(*args)

async def add_reaction_to_bot_messages(bot, channel_id):
    try:
        # Ensure your bot has 'Read Message History' permission
        channel = bot.cache.get_guild_channel(channel_id)
        if not channel:
            channel = await bot.rest.fetch_channel(channel_id)

        # Iterating through the messages in the channel
        async for message in bot.rest.fetch_messages(channel):
            if message.author.id == bot.get_me().id:  # Check if the message is from the bot
                await message.add_reaction('🗑️')  # Add reaction
                print(f"Added reaction to message ID: {message.id}")
    except Exception as e:
        print(f"An error occurred: {e}")

@bot.listen()
async def on_ready(event: hikari.StartingEvent) -> None:
    info("Starting event loop...")
    asyncio.create_task(check_alerts())

@bot.command
@lightbulb.option("name", "Name of the item to register.", required=True)
@lightbulb.command(
    "register", "Register a new alert for a ZenMarket item.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def register(ctx: lightbulb.SlashContext, name: str) -> None:
    if any(True for _ in bot.d.table.find(name=name)):
        await ctx.respond(f"Alert for **{name}** already exists!")
        return

    alert = {
        "channel_id": ctx.channel_id,
        "name": name,
    }
    bot.d.table.insert(alert)
    await ctx.respond(f"Registered alert for **{name}**!")
    # Run checks for the newly added alert
    await check_alerts([alert])


@bot.command
@lightbulb.option("name", "Name of the item to delete.", required=True)
@lightbulb.command("unregister", "Delete an alert", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def unregister(ctx: lightbulb.SlashContext, name: str) -> None:
    if not bot.d.table.find_one(name=name):
        await ctx.respond(f"Alert for **{name}** does not exist!")
        return

    bot.d.table.delete(name=name)
    await ctx.respond(f"Unregistered alert for **{name}**!")

@bot.command
@lightbulb.command("alerts", "List alerts")
@lightbulb.implements(lightbulb.SlashCommand)
async def alerts(ctx: lightbulb.SlashContext) -> None:
    alerts = bot.d.table.find()
    alerts = sorted(alerts, key=lambda alert: alert['name'])
    if all(False for _ in alerts):
        await ctx.respond("You have no alerts!")
        return

    await ctx.respond("\n".join([f"{alert['name']}" for alert in alerts]) or "None")

@bot.command
@lightbulb.option("count", "Number of the most recent messages by the bot to delete.", type=int, required=False, default=10)
@lightbulb.command("cleanup", "Cleans up messages sent by the bot in the channel.")
@lightbulb.implements(lightbulb.SlashCommand)
async def cleanup(ctx: lightbulb.SlashContext) -> None:
    count = ctx.options.count
    channel_id = ctx.channel_id
    bot_id = bot.get_me().id  # Fetch bot's own user ID

    # Create initial response
    await ctx.respond(f"Cleaning up {count} messages...")

    try:
        messages = await bot.rest.fetch_messages(channel_id)
        bot_messages = [msg for msg in messages if msg.author.id == bot_id]
        
        to_delete = bot_messages[:count]
        print(to_delete)
        if not to_delete:
            await ctx.edit_last_response("No messages by the bot found to delete.")
            return

        for message in to_delete:
            await bot.rest.delete_message(channel_id, message.id)

        await ctx.edit_last_response(f"Deleted {len(to_delete)} messages.")
    except hikari.ForbiddenError:
        await ctx.edit_last_response("I don't have the necessary permissions to delete messages.")
    except hikari.NotFoundError:
        await ctx.edit_last_response("Some messages were not found. They may have already been deleted.")
    except Exception as e:
        await ctx.edit_last_response(f"An unexpected error occurred: {e}")

@bot.command
@lightbulb.command("reacttocleanup", "Adds a delete reaction to all bot messages in a channel.")
@lightbulb.implements(lightbulb.SlashCommand)
async def react_to_cleanup(ctx: lightbulb.SlashContext) -> None:
    await add_reaction_to_bot_messages(bot, ctx.get_channel().id)
    await ctx.respond("Completed adding reactions to all bot messages in this channel.")

@bot.listen(hikari.ReactionAddEvent)
async def on_reaction_add(event: hikari.ReactionAddEvent):
    if event.user_id == bot.get_me().id:
        return  # Ignore reactions added by the bot

    # Check if the reaction is the designated delete reaction
    if event.emoji_name == '🗑️':
        channel_id = event.channel_id
        message_id = event.message_id

        # Fetch the message to verify it was sent by the bot
        message = await bot.rest.fetch_message(channel_id, message_id)
        if message.author.id == bot.get_me().id:
            item = bot.d.synced.find_one(message_id=message_id)
            if item:
                bot.d.blacklist.insert({
                    "item_id": item["name"],
                    "channel_id": message.channel_id
                })

            await bot.rest.delete_message(channel_id, message_id)
            info(f"[Reaction Listener] Message {message_id} deleted after reaction.")

if __name__ == "__main__":
    bot.run(
        propagate_interrupts=True,      # Any OS interrupts get rethrown as errors.
        coroutine_tracking_depth=30,
        asyncio_debug=True,
        activity=hikari.Activity(
            name="Posters", type=hikari.ActivityType.WATCHING
        )
    )
