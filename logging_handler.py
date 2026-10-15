import logging
import asyncio
import hikari
from datetime import datetime
from typing import Optional, List
from collections import deque
import re

class DiscordLogHandler(logging.Handler):
    """
    A logging handler that sends log messages to a Discord channel with buffering
    and Discord-specific formatting.
    """
    
    def __init__(self, bot: hikari.GatewayBot, level=logging.INFO):
        super().__init__(level)
        self.bot = bot
        self.target_channel_id: Optional[int] = None
        self.enabled = False
        self.buffer: deque = deque(maxlen=50)  # Buffer up to 50 log entries
        self.buffer_task: Optional[asyncio.Task] = None
        self.flush_interval = 10.0  # Flush buffer every 10 seconds
        self.max_message_length = 1900  # Leave room for Discord formatting
        
        # Log level emojis and colors
        self.level_config = {
            logging.DEBUG: {"emoji": "🔍", "name": "DEBUG", "color": hikari.Color(0x808080)},
            logging.INFO: {"emoji": "ℹ️", "name": "INFO", "color": hikari.Color(0x0099ff)},
            logging.WARNING: {"emoji": "⚠️", "name": "WARN", "color": hikari.Color(0xff9900)},
            logging.ERROR: {"emoji": "❌", "name": "ERROR", "color": hikari.Color(0xff0000)},
            logging.CRITICAL: {"emoji": "🚨", "name": "CRIT", "color": hikari.Color(0x990000)},
        }
        
        # Set up formatter for structured logging
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%H:%M:%S'
        )
        self.setFormatter(formatter)
    
    def enable_logging(self, channel_id: int) -> bool:
        """Enable Discord logging to the specified channel."""
        try:
            self.target_channel_id = channel_id
            self.enabled = True
            
            # Start the buffer flush task
            if self.buffer_task is None or self.buffer_task.done():
                self.buffer_task = asyncio.create_task(self._buffer_flush_loop())
            
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to enable Discord logging: {e}")
            return False
    
    def disable_logging(self) -> bool:
        """Disable Discord logging and flush remaining buffer."""
        try:
            self.enabled = False
            
            # Cancel the buffer flush task
            if self.buffer_task and not self.buffer_task.done():
                self.buffer_task.cancel()
            
            # Flush any remaining logs
            if self.buffer:
                asyncio.create_task(self._flush_buffer())
            
            self.target_channel_id = None
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to disable Discord logging: {e}")
            return False
    
    def emit(self, record: logging.LogRecord) -> None:
        """Handle a log record by adding it to the buffer."""
        if not self.enabled or not self.target_channel_id:
            return
        
        try:
            # Format the log record
            formatted_message = self.format(record)
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created),
                'level': record.levelno,
                'message': formatted_message,
                'record': record
            }
            
            # Add to buffer
            self.buffer.append(log_entry)
            
        except Exception as e:
            # Don't use logging here to avoid recursion
            print(f"Discord log handler error: {e}")
    
    async def _buffer_flush_loop(self) -> None:
        """Background task that periodically flushes the log buffer."""
        try:
            while self.enabled:
                await asyncio.sleep(self.flush_interval)
                if self.buffer:
                    await self._flush_buffer()
        except asyncio.CancelledError:
            # Final flush before cancellation
            if self.buffer:
                await self._flush_buffer()
            raise
        except Exception as e:
            logging.getLogger(__name__).error(f"Buffer flush loop error: {e}")
    
    async def _flush_buffer(self) -> None:
        """Flush the current buffer to Discord."""
        if not self.buffer or not self.enabled or not self.target_channel_id:
            return
        
        try:
            # Get all buffered entries
            entries = list(self.buffer)
            self.buffer.clear()
            
            # Group entries by severity for better organization
            grouped_entries = self._group_entries_by_level(entries)
            
            # Send grouped messages
            for level, level_entries in grouped_entries.items():
                if level_entries:
                    await self._send_log_group(level, level_entries)
                    
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to flush buffer to Discord: {e}")
    
    def _group_entries_by_level(self, entries: List[dict]) -> dict:
        """Group log entries by their severity level."""
        groups = {
            logging.DEBUG: [],
            logging.INFO: [],
            logging.WARNING: [],
            logging.ERROR: [],
            logging.CRITICAL: []
        }
        
        for entry in entries:
            level = entry['level']
            if level in groups:
                groups[level].append(entry)
        
        return groups
    
    async def _send_log_group(self, level: int, entries: List[dict]) -> None:
        """Send a group of log entries of the same level to Discord."""
        if not entries:
            return
        
        level_info = self.level_config.get(level, self.level_config[logging.INFO])
        
        # Build the message content
        header = f"{level_info['emoji']} **{level_info['name']} Logs** ({len(entries)} entries)"
        
        # Create code block with log entries
        log_lines = []
        for entry in entries:
            # Clean and truncate individual log lines
            cleaned_message = self._clean_message(entry['message'])
            log_lines.append(cleaned_message)
        
        # Split into multiple messages if needed
        message_chunks = self._split_into_chunks(log_lines, header)
        
        # Send each chunk
        for i, chunk in enumerate(message_chunks):
            try:
                if len(message_chunks) > 1:
                    chunk_header = f"{header} (Part {i+1}/{len(message_chunks)})"
                else:
                    chunk_header = header
                
                # Create embed for better formatting
                embed = hikari.Embed(
                    title=chunk_header,
                    description=f"```\n{chunk}\n```",
                    color=level_info['color'],
                    timestamp=datetime.now()
                )
                
                await self.bot.rest.create_message(
                    self.target_channel_id, 
                    embed=embed
                )
                
                # Small delay between messages to avoid rate limits
                if i < len(message_chunks) - 1:
                    await asyncio.sleep(0.5)
                    
            except hikari.RateLimitTooLongError:
                # If we hit rate limits, wait and try again
                await asyncio.sleep(5)
                await self.bot.rest.create_message(
                    self.target_channel_id,
                    f"⚠️ **Log Rate Limited** - Some {level_info['name']} logs may have been skipped"
                )
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to send log message: {e}")
    
    def _clean_message(self, message: str) -> str:
        """Clean and format a log message for Discord."""
        # Remove ANSI color codes if any
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        cleaned = ansi_escape.sub('', message)
        
        # Escape Discord markdown
        cleaned = cleaned.replace('`', '\'').replace('*', '✱').replace('_', '—')
        
        # Truncate very long lines
        if len(cleaned) > 200:
            cleaned = cleaned[:197] + "..."
        
        return cleaned
    
    def _split_into_chunks(self, log_lines: List[str], header: str) -> List[str]:
        """Split log lines into chunks that fit Discord message limits."""
        chunks = []
        current_chunk = []
        current_length = 0
        
        # Account for embed overhead and markdown
        max_chunk_length = self.max_message_length - len(header) - 50
        
        for line in log_lines:
            line_length = len(line) + 1  # +1 for newline
            
            if current_length + line_length > max_chunk_length and current_chunk:
                # Finish current chunk and start new one
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_length = line_length
            else:
                current_chunk.append(line)
                current_length += line_length
        
        # Add the last chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        return chunks if chunks else ["No log content"]
    
    def get_status(self) -> dict:
        """Get the current status of the Discord logging handler."""
        return {
            'enabled': self.enabled,
            'target_channel_id': self.target_channel_id,
            'buffer_size': len(self.buffer),
            'buffer_task_running': self.buffer_task is not None and not self.buffer_task.done(),
            'flush_interval': self.flush_interval
        }


# Global instance that will be initialized in main.py
discord_log_handler: Optional[DiscordLogHandler] = None

def setup_discord_logging(bot: hikari.GatewayBot, level=logging.INFO) -> DiscordLogHandler:
    """Initialize the Discord logging handler and attach it to the root logger."""
    global discord_log_handler
    
    discord_log_handler = DiscordLogHandler(bot, level)
    
    # Add the handler to the root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(discord_log_handler)
    
    return discord_log_handler

def get_discord_log_handler() -> Optional[DiscordLogHandler]:
    """Get the global Discord log handler instance."""
    return discord_log_handler 