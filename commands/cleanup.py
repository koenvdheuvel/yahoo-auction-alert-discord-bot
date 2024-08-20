import lightbulb
from commands.base import BaseCommand
import hikari

class CleanupCommand(BaseCommand):
    def register(self):
        @self.bot.command
        @lightbulb.option(
            "count", 
            "Number of the most recent messages by the bot to delete.", 
            type=int, 
            required=False, 
            default=10
        )
        @lightbulb.command("cleanup", "Cleans up messages sent by the bot in the channel.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def cleanup(ctx: lightbulb.SlashContext) -> None:
            count = ctx.options.count
            channel_id = ctx.channel_id
            bot_id = self.bot.get_me().id  # Fetch bot's own user ID

            # Create initial response
            await ctx.respond(f"Cleaning up {count} messages...")

            try:
                messages = await self.bot.rest.fetch_messages(channel_id)
                bot_messages = [msg for msg in messages if msg.author.id == bot_id]
                
                to_delete = bot_messages[:count]
                if not to_delete:
                    await ctx.edit_last_response("No messages by the bot found to delete.")
                    return

                for message in to_delete:
                    await self.bot.rest.delete_message(channel_id, message.id)

                await ctx.edit_last_response(f"Deleted {len(to_delete)} messages.")
            except hikari.ForbiddenError:
                await ctx.edit_last_response("I don't have the necessary permissions to delete messages.")
            except hikari.NotFoundError:
                await ctx.edit_last_response("Some messages were not found. They may have already been deleted.")
            except Exception as e:
                await ctx.edit_last_response(f"An unexpected error occurred: {e}")
