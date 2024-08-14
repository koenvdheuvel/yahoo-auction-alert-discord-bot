import lightbulb
from commands.base import BaseCommand
from models import Alert

class AllAlertsCommand(BaseCommand):
    def register(self):
        @self.bot.command
        @lightbulb.command("allalerts", "List alerts for all channels")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def allalerts(ctx: lightbulb.SlashContext) -> None:
            alerts = Alert.select().order_by(Alert.channel_id)
            
            if not alerts:
                await ctx.respond("You have no alerts!")
                return

            # Generate the alert list
            alert_list = "\n".join([f"<#{alert.channel_id}> {alert.search_query}" for alert in alerts])
            
            def split_message_on_newlines(message: str, max_length: int) -> list:
                lines = message.split('\n')
                chunks = []
                current_chunk = ""
                
                for line in lines:
                    # If adding this line exceeds the max_length, save the current chunk and start a new one
                    if len(current_chunk) + len(line) + 1 > max_length:
                        chunks.append(current_chunk)
                        current_chunk = line
                    else:
                        if current_chunk:
                            current_chunk += '\n'
                        current_chunk += line
                
                if current_chunk:
                    chunks.append(current_chunk)
                
                return chunks

            messages = split_message_on_newlines(alert_list, 2000)
            
            # Send each chunk as a separate message
            for message in messages:
                await ctx.respond(message)
