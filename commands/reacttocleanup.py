import lightbulb
from commands.base import BaseCommand

class ReactToCleanupCommand(BaseCommand):
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

    def register(self):
        @self.bot.command
        @lightbulb.command("reacttocleanup", "Adds a delete reaction to all bot messages in a channel.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def react_to_cleanup(ctx: lightbulb.SlashContext) -> None:
            await self.add_reaction_to_bot_messages(self.bot, ctx.get_channel().id)
            await ctx.respond("Completed adding reactions to all bot messages in this channel.")
