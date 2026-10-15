import lightbulb
import hikari
from logging import info
from commands.base import BaseCommand
from logging_handler import get_discord_log_handler

class DiscordLoggingCommands(BaseCommand):
    def __init__(self, bot: lightbulb.BotApp):
        super().__init__(bot)
    
    def register(self):
        @self.bot.command
        @lightbulb.command("enablelogs", "Enable Discord logging to this channel")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def enable_discord_logging(ctx: lightbulb.Context) -> None:
            author_info = f"user {ctx.author} ({ctx.author.id})"
            channel_id = ctx.channel_id
            info(f"Enable Discord logging command received from {author_info} in channel {channel_id}")
            
            # Get the Discord log handler
            log_handler = get_discord_log_handler()
            if not log_handler:
                await ctx.respond("❌ Discord logging system is not initialized. Please contact an administrator.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Check if already enabled
            if log_handler.enabled and log_handler.target_channel_id == channel_id:
                await ctx.respond("📋 Discord logging is already enabled for this channel.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Enable logging for this channel
            success = log_handler.enable_logging(channel_id)
            
            if success:
                response = f"✅ **Discord Logging Enabled**\n"
                response += f"📍 Target Channel: <#{channel_id}>\n"
                response += f"🔄 Flush Interval: {log_handler.flush_interval}s\n"
                response += f"📊 Buffer Size: {log_handler.buffer.maxlen} entries\n\n"
                response += f"All application logs will now be sent to this channel in organized, formatted messages."
                
                await ctx.respond(response, flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Discord logging enabled for channel {channel_id} by {author_info}")
                
                # Send a test log message to demonstrate
                info("Discord logging test: System successfully configured!")
            else:
                await ctx.respond("❌ Failed to enable Discord logging. Please check the logs for details.", flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Failed to enable Discord logging for channel {channel_id} by {author_info}")

        @self.bot.command
        @lightbulb.command("disablelogs", "Disable Discord logging")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def disable_discord_logging(ctx: lightbulb.Context) -> None:
            author_info = f"user {ctx.author} ({ctx.author.id})"
            info(f"Disable Discord logging command received from {author_info}")
            
            # Get the Discord log handler
            log_handler = get_discord_log_handler()
            if not log_handler:
                await ctx.respond("❌ Discord logging system is not initialized.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Check if already disabled
            if not log_handler.enabled:
                await ctx.respond("📋 Discord logging is already disabled.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Get current status for the response
            old_channel_id = log_handler.target_channel_id
            buffer_size = len(log_handler.buffer)
            
            # Disable logging
            success = log_handler.disable_logging()
            
            if success:
                response = f"🔴 **Discord Logging Disabled**\n"
                if old_channel_id:
                    response += f"📍 Previous Channel: <#{old_channel_id}>\n"
                if buffer_size > 0:
                    response += f"📤 Flushing {buffer_size} buffered log(s)\n"
                response += f"\nDiscord logging has been stopped and remaining logs have been sent."
                
                await ctx.respond(response, flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Discord logging disabled by {author_info}. Previous channel: {old_channel_id}")
            else:
                await ctx.respond("❌ Failed to disable Discord logging. Please check the logs for details.", flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Failed to disable Discord logging by {author_info}")

        @self.bot.command
        @lightbulb.command("logstatus", "Check the status of Discord logging")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def discord_logging_status(ctx: lightbulb.Context) -> None:
            author_info = f"user {ctx.author} ({ctx.author.id})"
            info(f"Discord logging status command received from {author_info}")
            
            # Get the Discord log handler
            log_handler = get_discord_log_handler()
            if not log_handler:
                await ctx.respond("❌ Discord logging system is not initialized.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Get current status
            status = log_handler.get_status()
            
            # Build status response
            if status['enabled']:
                response = f"✅ **Discord Logging - ACTIVE**\n"
                response += f"📍 Target Channel: <#{status['target_channel_id']}>\n"
                response += f"📊 Buffer: {status['buffer_size']}/{log_handler.buffer.maxlen} entries\n"
                response += f"🔄 Flush Interval: {status['flush_interval']}s\n"
                response += f"⚡ Buffer Task: {'Running' if status['buffer_task_running'] else 'Stopped'}\n"
                
                # Show log level configuration
                response += f"\n**📋 Log Levels:**\n"
                for level, config in log_handler.level_config.items():
                    level_name = config['name']
                    emoji = config['emoji']
                    response += f"{emoji} {level_name}\n"
                    
            else:
                response = f"🔴 **Discord Logging - DISABLED**\n"
                response += f"📊 Buffer: {status['buffer_size']} entries (will be lost)\n"
                response += f"💡 Use `/enablelogs` in a channel to start logging"
            
            await ctx.respond(response, flags=hikari.MessageFlag.EPHEMERAL)

        @self.bot.command
        @lightbulb.command("flushlogs", "Manually flush the log buffer to Discord")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def flush_log_buffer(ctx: lightbulb.Context) -> None:
            author_info = f"user {ctx.author} ({ctx.author.id})"
            info(f"Manual log flush command received from {author_info}")
            
            # Get the Discord log handler
            log_handler = get_discord_log_handler()
            if not log_handler:
                await ctx.respond("❌ Discord logging system is not initialized.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            if not log_handler.enabled:
                await ctx.respond("❌ Discord logging is not enabled. Use `/enablelogs` first.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            buffer_size = len(log_handler.buffer)
            
            if buffer_size == 0:
                await ctx.respond("📋 Log buffer is empty - nothing to flush.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Manually flush the buffer
            try:
                await log_handler._flush_buffer()
                await ctx.respond(f"📤 Successfully flushed {buffer_size} log entries to <#{log_handler.target_channel_id}>.", flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Manual log buffer flush completed by {author_info}. Flushed {buffer_size} entries.")
            except Exception as e:
                await ctx.respond(f"❌ Failed to flush log buffer: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Manual log buffer flush failed by {author_info}: {e}")

        @self.bot.command
        @lightbulb.command("testlogs", "Send test log messages to verify Discord logging")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def test_discord_logging(ctx: lightbulb.Context) -> None:
            author_info = f"user {ctx.author} ({ctx.author.id})"
            info(f"Test Discord logging command received from {author_info}")
            
            # Get the Discord log handler
            log_handler = get_discord_log_handler()
            if not log_handler:
                await ctx.respond("❌ Discord logging system is not initialized.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            if not log_handler.enabled:
                await ctx.respond("❌ Discord logging is not enabled. Use `/enablelogs` first.", flags=hikari.MessageFlag.EPHEMERAL)
                return
            
            # Send test logs at different levels
            import logging
            test_logger = logging.getLogger("DiscordLogTest")
            
            test_logger.debug(f"DEBUG test message from {author_info}")
            test_logger.info(f"INFO test message from {author_info}")
            test_logger.warning(f"WARNING test message from {author_info}")
            test_logger.error(f"ERROR test message from {author_info}")
            
            await ctx.respond(f"📋 Test log messages sent! They should appear in <#{log_handler.target_channel_id}> within {log_handler.flush_interval} seconds.", flags=hikari.MessageFlag.EPHEMERAL)
            info(f"Discord logging test completed by {author_info}") 