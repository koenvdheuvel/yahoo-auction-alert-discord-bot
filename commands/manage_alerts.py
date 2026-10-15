"""
Alert Management Commands Module

This module provides Discord slash commands for managing alert checks, task interruption,
and scheduler control. It integrates with the TaskManager and APScheduler systems.
"""

import lightbulb
import hikari
import os
import asyncio # Added for task cancellation check
from logging import info
from apscheduler.job import Job # Import Job for type hinting if needed, and for job attributes
from lightbulb.utils import pag, nav
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any

from models import Alert
from commands.base import BaseCommand

# =============================================================================
# DEPENDENCY IMPORTS AND CONSTANTS
# =============================================================================

# Attempt to import necessary components from main.py and task_manager
# This relies on main.py having these defined at its top level and Python's import handling.
try:
    from main import scheduler, perform_single_alert_check
    from task_manager import get_task_manager, TaskStatus
    info("AlertManagementCommands: Successfully imported dependencies from main and task_manager.")
except ImportError as e:
    info(f"CRITICAL: AlertManagementCommands failed to import dependencies: {e}. Commands may not work.")
    # Define as None so runtime checks can fail gracefully
    scheduler = None
    perform_single_alert_check = None
    get_task_manager = None
    TaskStatus = None

# =============================================================================
# MAIN CLASS
# =============================================================================

class AlertManagementCommands(BaseCommand):
    """
    Discord slash commands for alert management and task control.
    
    Provides commands for:
    - Manual alert checking
    - Task interruption and cancellation
    - Scheduler control
    - Status monitoring
    """
    
    def __init__(self, bot: lightbulb.BotApp):
        super().__init__(bot)
        # Check if dependencies were loaded, log if not.
        if scheduler is None or perform_single_alert_check is None or get_task_manager is None or TaskStatus is None:
            info("AlertManagementCommands initialized, but critical dependencies (scheduler, check function, or task tracker) are missing. Commands will fail or be unstable.")
    
    # =============================================================================
    # VALIDATION AND UTILITY HELPERS
    # =============================================================================
    
    def _get_author_info(self, ctx: lightbulb.Context) -> str:
        """Generate standardized author info string for logging."""
        return f"user {ctx.author} ({ctx.author.id})"
    
    async def _validate_dependencies(self, ctx: lightbulb.Context, need_scheduler: bool = False, need_tasks: bool = False) -> bool:
        """
        Validate that required dependencies are available.
        
        Args:
            ctx: Discord context
            need_scheduler: Whether scheduler functionality is required
            need_tasks: Whether task manager functionality is required
            
        Returns:
            bool: True if all required dependencies are available
        """
        if need_scheduler and (scheduler is None or perform_single_alert_check is None):
            await ctx.respond("Error: The alert scheduling system is not properly initialized.", flags=hikari.MessageFlag.EPHEMERAL)
            return False
        
        if need_tasks and get_task_manager is None:
            await ctx.respond("Error: The active task tracking system is not properly initialized.", flags=hikari.MessageFlag.EPHEMERAL)
            return False
        
        return True
    
    async def _parse_and_validate_alert(self, ctx: lightbulb.Context, alert_id_str: str, author_info: str) -> Tuple[Optional[int], Optional[Alert]]:
        """
        Parse alert ID string and fetch alert, with comprehensive error handling.
        
        Args:
            ctx: Discord context
            alert_id_str: String representation of alert ID
            author_info: Author information for logging
            
        Returns:
            Tuple of (alert_id, alert) or (None, None) if invalid/not found
        """
        try:
            alert_id = int(alert_id_str)
        except ValueError:
            await ctx.respond(f"Invalid alert target: '{alert_id_str}'. Please select a valid alert from the list.", flags=hikari.MessageFlag.EPHEMERAL)
            return None, None

        try:
            alert = Alert.get_by_id(alert_id)
            if not alert:
                await ctx.respond(f"Alert with ID {alert_id} not found. It might have been recently deleted.", flags=hikari.MessageFlag.EPHEMERAL)
                return None, None
            return alert_id, alert
        except Exception as e:
            info(f"Error fetching alert ID {alert_id} by {author_info}: {e}")
            await ctx.respond(f"An error occurred while trying to find alert ID {alert_id}.", flags=hikari.MessageFlag.EPHEMERAL)
            return None, None
    
    def _format_alert_name(self, alert_id: int) -> str:
        """Get a formatted alert name, falling back to ID if fetch fails."""
        try:
            alert = Alert.get_by_id(alert_id)
            return alert.search_query if alert else f"Alert {alert_id}"
        except:
            return f"Alert {alert_id}"
    
    # =============================================================================
    # RESPONSE HELPERS
    # =============================================================================
    
    async def _send_paginated_response(self, ctx: lightbulb.Context, lines: List[str], title: str = "Results") -> None:
        """Send a paginated response using lightbulb's pagination utilities."""
        if not lines:
            await ctx.respond("No data to display.", flags=hikari.MessageFlag.EPHEMERAL)
            return
        
        paginator = pag.StringPaginator(prefix=f"**{title}**\n", max_lines=20)
        for line in lines:
            paginator.add_line(line)
        
        navigator = nav.ButtonNavigator(paginator.build_pages())
        await navigator.run(ctx)
    
    async def _handle_task_cancellation_result(self, ctx: lightbulb.Context, cancelled_count: int, total_tasks: int, target_name: str) -> None:
        """Handle and respond with task cancellation results."""
        if cancelled_count > 0:
            success_msg = f"✅ Successfully interrupted {cancelled_count} check(s) for {target_name}. All tasks have been stopped."
            await ctx.edit_last_response(success_msg)
        else:
            await ctx.edit_last_response(f"❌ Found {total_tasks} task(s) for {target_name}, but none could be interrupted.")
    
    # =============================================================================
    # AUTOCOMPLETE HELPERS
    # =============================================================================
    
    async def _alert_target_autocomplete(self, option: hikari.CommandInteractionOption, interaction: hikari.AutocompleteInteraction):
        value = option.value
        if not isinstance(value, str):
            value = str(value)

        choices = []
        try:
            query = Alert.select(Alert.id, Alert.search_query)
            if value.isdigit():
                # Search by ID or if the search query contains the numeric string
                query = query.where((Alert.id == int(value)) | (Alert.search_query.contains(value)))
            elif value:
                # Search by search query if non-numeric
                query = query.where(Alert.search_query.contains(value))
            # If value is empty, query will fetch all (limited below)
            
            alerts_found = query.order_by(Alert.id.desc()).limit(25) # Show most recent first for empty/broad queries
            for alert_item in alerts_found:
                # Display name is descriptive, value submitted is the alert's ID as a string
                choices.append(hikari.CommandChoice(name=f"{alert_item.search_query} (ID: {alert_item.id})", value=str(alert_item.id)))
        except Exception as e:
            info(f"Autocomplete error for alert_target: {e}")
        
        return choices

    # =============================================================================
    # COMMAND IMPLEMENTATIONS
    # =============================================================================

    def register(self):
        @self.bot.command
        @lightbulb.option(
            "alert_target", 
            "The alert to check. Type search query or ID.", 
            type=str,  # Changed to str
            required=True,
            autocomplete=self._alert_target_autocomplete # Renamed and updated autocomplete function
        )
        @lightbulb.command("checkalert", "Manually schedules an immediate check for a specific alert.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def check_alert_manual(ctx: lightbulb.Context) -> None:
            alert_id_str = ctx.options.alert_target # This is now a string ID
            author_info = self._get_author_info(ctx)
            info(f"Manual trigger: Received /checkalert for alert_target: '{alert_id_str}' from {author_info}")

            if not await self._validate_dependencies(ctx, need_scheduler=True):
                return

            # Check if scheduler is running and start it if needed
            scheduler_was_started = False
            if not scheduler.running:
                try:
                    scheduler.start()
                    scheduler_was_started = True
                    info(f"Manual trigger: Started scheduler for alert check by {author_info}")
                except Exception as e:
                    info(f"Manual trigger: Failed to start scheduler: {e}")
                    await ctx.respond("Error: Could not start the scheduler. Please contact an administrator.", flags=hikari.MessageFlag.EPHEMERAL)
                    return

            try:
                alert_id, alert = await self._parse_and_validate_alert(ctx, alert_id_str, author_info)
                if alert_id is None:
                    return
            except Exception as e:
                info(f"Error in _parse_and_validate_alert: {e}")
                await ctx.respond(f"An error occurred while trying to find alert ID {alert_id}.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            try:
                task_manager = get_task_manager()
                task_id = task_manager.schedule_alert_check(alert_id, alert.search_query)
                
                if task_id is None:
                    # Task was skipped due to deduplication
                    response_msg = f"⚠️ Check for alert '{alert.search_query}' (ID: {alert.id}) was skipped - another check is already running or scheduled."
                    if scheduler_was_started:
                        response_msg += "\n🚀 Scheduler was automatically started."
                    await ctx.respond(response_msg, flags=hikari.MessageFlag.EPHEMERAL)
                    info(f"Manual trigger: Skipped duplicate check for alert ID: {alert_id} ('{alert.search_query}') by {author_info}. Scheduler started: {scheduler_was_started}")
                else:
                    # Build response message
                    response_msg = f"✅ Scheduled check for alert '{alert.search_query}' (ID: {alert.id})\n📋 Task ID: `{task_id}`"
                    if scheduler_was_started:
                        response_msg += "\n🚀 Scheduler was automatically started."
                    
                    await ctx.respond(response_msg, flags=hikari.MessageFlag.EPHEMERAL)
                    info(f"Manual trigger: Scheduled check for alert ID: {alert_id} ('{alert.search_query}') as task {task_id} by {author_info}. Scheduler started: {scheduler_was_started}")
            except Exception as e:
                info(f"Manual trigger: Failed to schedule check for alert ID {alert_id} ('{alert.search_query}') by {author_info}: {e}")
                await ctx.respond(f"Failed to schedule the check for alert ID {alert_id}. Please see logs.", flags=hikari.MessageFlag.EPHEMERAL)
        
        @self.bot.command
        @lightbulb.option(
            "alert_target",
            "The alert for which to stop scheduled checks. Type search query or ID.",
            type=str,
            required=True,
            autocomplete=self._alert_target_autocomplete
        )
        @lightbulb.command("stopalertcheck", "Stops/unschedules currently scheduled checks for a specific alert.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def stop_alert_check_manual(ctx: lightbulb.Context) -> None:
            alert_id_str = ctx.options.alert_target
            author_info = self._get_author_info(ctx)
            info(f"Stop command: Received /stopalertcheck for alert_target: '{alert_id_str}' from {author_info}")

            if not await self._validate_dependencies(ctx, need_scheduler=True):
                return

            try:
                alert_id, alert = await self._parse_and_validate_alert(ctx, alert_id_str, author_info)
                if alert_id is None:
                    return
            except Exception as e:
                info(f"Error in _parse_and_validate_alert: {e}")
                await ctx.respond(f"An error occurred while trying to find alert ID {alert_id}.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            removed_count = 0
            found_jobs_for_alert = False
            alert_search_query = self._format_alert_name(alert_id)

            try:
                for job in scheduler.get_jobs():
                    # Check if the job's target function is perform_single_alert_check
                    # and if the first argument (alert_id) matches.
                    if job.func == perform_single_alert_check and job.args and len(job.args) > 0 and job.args[0] == alert_id:
                        found_jobs_for_alert = True
                        try:
                            scheduler.remove_job(job.id)
                            removed_count += 1
                            info(f"Stop command: Removed job ID '{job.id}' for alert ID {alert_id} ('{alert_search_query}') by {author_info}.")
                        except Exception as e_remove:
                            info(f"Stop command: Failed to remove job ID '{job.id}' for alert ID {alert_id} ('{alert_search_query}'): {e_remove}")
                
                if not found_jobs_for_alert:
                    await ctx.respond(f"No currently scheduled checks found for alert '{alert_search_query}' (ID: {alert_id}).", flags=hikari.MessageFlag.EPHEMERAL)
                elif removed_count > 0:
                    await ctx.respond(f"Successfully removed {removed_count} scheduled check(s) for alert '{alert_search_query}' (ID: {alert_id}).", flags=hikari.MessageFlag.EPHEMERAL)
                else:
                    await ctx.respond(f"Found scheduled checks for alert '{alert_search_query}' (ID: {alert_id}), but failed to remove them. See logs.", flags=hikari.MessageFlag.EPHEMERAL)
            except Exception as e_get_jobs:
                info(f"Stop command: Error while iterating or removing jobs for alert ID {alert_id} ('{alert_search_query}'): {e_get_jobs}")
                await ctx.respond("An error occurred while trying to stop scheduled checks. Please see logs.", flags=hikari.MessageFlag.EPHEMERAL)

        @self.bot.command
        @lightbulb.option(
            "alert_target",
            "The alert for which to interrupt currently running checks. Type search query or ID.",
            type=str,
            required=True,
            autocomplete=self._alert_target_autocomplete
        )
        @lightbulb.command("interruptalert", "Attempts to interrupt any currently running checks for a specific alert.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def interrupt_alert_manual(ctx: lightbulb.Context) -> None:
            alert_id_str = ctx.options.alert_target
            author_info = self._get_author_info(ctx)
            info(f"Interrupt command: Received /interruptalert for alert_target: '{alert_id_str}' from {author_info}")

            if not await self._validate_dependencies(ctx, need_tasks=True):
                return

            try:
                alert_id, alert = await self._parse_and_validate_alert(ctx, alert_id_str, author_info)
                if alert_id is None:
                    return
            except Exception as e:
                info(f"Error in _parse_and_validate_alert: {e}")
                await ctx.respond(f"An error occurred while trying to find alert ID {alert_id}.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            alert_search_query = self._format_alert_name(alert_id)
            task_manager = get_task_manager()
            
            # Get tasks for this alert that can be cancelled
            tasks_for_alert = task_manager.get_tasks_by_alert(alert_id)
            active_tasks = [task for task in tasks_for_alert if task.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]]

            if not active_tasks:
                await ctx.respond(f"No currently running or scheduled checks found for alert '{alert_search_query}' (ID: {alert_id}).", flags=hikari.MessageFlag.EPHEMERAL)
                info(f"Interrupt command: No active tasks found for alert ID {alert_id} ('{alert_search_query}') for {author_info}.")
                return

            info(f"Interrupt command: Attempting to cancel {len(active_tasks)} tasks for alert ID {alert_id} ('{alert_search_query}') by {author_info}.")
            
            # Send initial response
            await ctx.respond(f"Attempting to interrupt {len(active_tasks)} check(s) for alert '{alert_search_query}' (ID: {alert_id})...", flags=hikari.MessageFlag.EPHEMERAL)
            
            # Cancel tasks using TaskManager with async waiting
            try:
                cancelled_count = await task_manager.cancel_tasks_for_alert_async(alert_id)
                
                await self._handle_task_cancellation_result(ctx, cancelled_count, len(active_tasks), alert_search_query)
            except Exception as e:
                error_msg = f"❌ Error occurred while interrupting tasks for alert '{alert_search_query}' (ID: {alert_id}). See logs for details."
                await ctx.edit_last_response(error_msg)
                info(f"Interrupt command: Error during cancellation for alert ID {alert_id}: {e}")

        @self.bot.command
        @lightbulb.command("taskstatus", "Shows the status of currently running alert check tasks.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def task_status(ctx: lightbulb.Context) -> None:
            author_info = self._get_author_info(ctx)
            info(f"Task status command received from {author_info}")

            if not await self._validate_dependencies(ctx, need_tasks=True):
                return

            task_manager = get_task_manager()
            
            # Get task summary
            summary = task_manager.get_summary()
            all_tasks = task_manager.get_all_tasks()
            
            # Get scheduler info
            scheduler_info = task_manager.get_scheduler_jobs_info()
            
            status_lines = []
            
            # Add scheduler information
            if "error" not in scheduler_info:
                status_lines.append(f"🔧 **Scheduler Status**: {'RUNNING' if scheduler_info['scheduler_running'] else 'STOPPED'}")
                status_lines.append(f"📅 **Scheduled Jobs**: {scheduler_info['total_jobs']}")
                
                if scheduler_info['jobs']:
                    status_lines.append("**Recent/Upcoming Jobs:**")
                    for job in scheduler_info['jobs'][:5]:  # Show up to 5 jobs
                        next_run = "Now" if not job['next_run'] else f"<t:{int(datetime.fromisoformat(job['next_run']).timestamp())}:R>"
                        paused_indicator = " (PAUSED)" if job.get('paused', False) else ""
                        status_lines.append(f"• {job['id']}: {next_run}{paused_indicator}")
                else:
                    status_lines.append("**No scheduled jobs found**")
            else:
                status_lines.append(f"❌ **Scheduler Error**: {scheduler_info['error']}")
            
            status_lines.append("")  # Empty line separator
            
            # Add task summary
            total_tasks = len(all_tasks)
            if total_tasks == 0:
                status_lines.append("📋 **Currently Tracked Tasks**: None")
                status_lines.append("")
                status_lines.append("**💡 This is normal when:**")
                status_lines.append("• No alerts are currently running checks")
                status_lines.append("• All recent checks completed quickly")
                status_lines.append("• Scheduler is between cycles")
                status_lines.append("")
                status_lines.append("**🔍 To see activity:**")
                status_lines.append("• Use `/enablelogs` to see real-time activity")
                status_lines.append("• Wait for the next scheduled check cycle")
            else:
                status_lines.append(f"📊 **Task Summary** (Total: {total_tasks})")
                for status_name, count in summary.items():
                    if count > 0:
                        emoji = {"scheduled": "⏰", "running": "🔄", "completed": "✅", "failed": "❌", "cancelled": "🛑"}.get(status_name, "📋")
                        status_lines.append(f"{emoji} {status_name.title()}: {count}")
                
                status_lines.append("")
                status_lines.append("**📋 Task Details:**")
                
                # Group tasks by status
                for status in [TaskStatus.RUNNING, TaskStatus.SCHEDULED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    tasks_in_status = task_manager.get_tasks_by_status(status)
                    if tasks_in_status:
                        status_lines.append(f"**{status.value.title()} Tasks:**")
                        for task in tasks_in_status[:5]:  # Limit to 5 per status
                            age_str = f"{task.age:.1f}s ago"
                            duration_str = f" ({task.duration:.1f}s)" if task.duration else ""
                            status_lines.append(f"• {task.alert_name} (ID: {task.alert_id}){duration_str} - {age_str}")
                        
                        if len(tasks_in_status) > 5:
                            status_lines.append(f"  ... and {len(tasks_in_status) - 5} more")
                        status_lines.append("")
            
            # Use pagination for larger responses
            if len(status_lines) > 15:
                await self._send_paginated_response(ctx, status_lines, "Task Status")
            else:
                response = "\n".join(status_lines)
                await ctx.respond(response, flags=hikari.MessageFlag.EPHEMERAL)
            
            info(f"Task status: Provided status to {author_info}. Total tasks: {total_tasks}, Summary: {summary}")

        @self.bot.command
        @lightbulb.command("interruptchannel", "Interrupts all currently running alert checks for this channel.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def interrupt_channel_tasks(ctx: lightbulb.Context) -> None:
            author_info = self._get_author_info(ctx)
            channel_id = ctx.channel_id
            info(f"Interrupt channel command received from {author_info} in channel {channel_id}")

            if not await self._validate_dependencies(ctx, need_tasks=True):
                return

            task_manager = get_task_manager()
            all_tasks = task_manager.get_all_tasks()
            
            if not all_tasks:
                await ctx.respond("No currently tracked tasks in any channel.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all alerts for this channel
            try:
                channel_alerts = Alert.select().where(Alert.channel_id == channel_id)
                channel_alert_ids = [alert.id for alert in channel_alerts]
                
                if not channel_alert_ids:
                    await ctx.respond("No alerts found for this channel.", flags=hikari.MessageFlag.EPHEMERAL)
                    return
                
                info(f"Found {len(channel_alert_ids)} alerts for channel {channel_id}: {channel_alert_ids}")
                
            except Exception as e:
                info(f"Error fetching alerts for channel {channel_id}: {e}")
                await ctx.respond("Error fetching alerts for this channel.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get tasks for this channel's alerts
            channel_tasks = task_manager.get_tasks_by_alerts(channel_alert_ids)
            active_tasks = [task for task in channel_tasks if task.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]]

            if not active_tasks:
                await ctx.respond(f"No currently running or scheduled tasks found for {len(channel_alert_ids)} alert(s) in this channel.", flags=hikari.MessageFlag.EPHEMERAL)
                info(f"No active tasks found for channel {channel_id} alerts: {channel_alert_ids}")
                return

            # Send initial response
            await ctx.respond(f"Attempting to interrupt {len(active_tasks)} task(s) across {len(channel_alert_ids)} alert(s) in this channel...", flags=hikari.MessageFlag.EPHEMERAL)
            
            # Cancel tasks using TaskManager with async waiting
            try:
                cancelled_count = await task_manager.cancel_tasks_for_channel_async(channel_id, channel_alert_ids)

                await self._handle_task_cancellation_result(ctx, cancelled_count, len(active_tasks), f"<#{channel_id}>")
            except Exception as e:
                error_msg = f"❌ Error occurred while interrupting tasks for this channel. See logs for details."
                await ctx.edit_last_response(error_msg)
                info(f"Interrupt channel: Error during cancellation for channel {channel_id}: {e}")

        @self.bot.command
        @lightbulb.command("channelstatus", "Shows the status of alert check tasks for this channel only.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def channel_task_status(ctx: lightbulb.Context) -> None:
            author_info = self._get_author_info(ctx)
            channel_id = ctx.channel_id
            info(f"Channel status command received from {author_info} in channel {channel_id}")

            if not await self._validate_dependencies(ctx, need_tasks=True):
                return

            task_manager = get_task_manager()
            
            # Find all alerts for this channel
            try:
                channel_alerts = Alert.select().where(Alert.channel_id == channel_id)
                channel_alert_ids = [alert.id for alert in channel_alerts]
                
                info(f"Channel status: Found {len(channel_alert_ids)} alerts for channel {channel_id}: {channel_alert_ids}")
                
                if not channel_alert_ids:
                    await ctx.respond("No alerts configured for this channel.", flags=hikari.MessageFlag.EPHEMERAL)
                    return
                
            except Exception as e:
                info(f"Error fetching alerts for channel {channel_id}: {e}")
                await ctx.respond("Error fetching alerts for this channel.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get tasks for this channel's alerts
            channel_tasks = task_manager.get_tasks_by_alerts(channel_alert_ids)
            
            if not channel_tasks:
                response_lines = [
                    f"**📋 Channel Status - No Tasks**",
                    f"Found {len(channel_alert_ids)} alert(s) configured for this channel, but no tracked tasks.",
                    f"",
                    f"**Configured alerts:**"
                ]
                for alert_id in channel_alert_ids:
                    alert_name = self._format_alert_name(alert_id)
                    response_lines.append(f"• {alert_name} (ID: {alert_id})")
                
                response_lines.extend([
                    f"",
                    f"**💡 To see tasks:**",
                    f"• Use `/checkalert [alert]` to trigger a specific check",
                    f"• Wait for the next scheduled check cycle"
                ])
            else:
                # Group tasks by status and alert
                task_summary = {}
                for task in channel_tasks:
                    alert_id = task.alert_id
                    if alert_id not in task_summary:
                        task_summary[alert_id] = {
                            "alert_name": task.alert_name,
                            "scheduled": 0,
                            "running": 0,
                            "completed": 0,
                            "failed": 0,
                            "cancelled": 0
                        }
                    task_summary[alert_id][task.status.value] += 1
                
                total_tasks = len(channel_tasks)
                status_counts = task_manager.get_summary()
                channel_status_counts = {status: 0 for status in status_counts.keys()}
                for task in channel_tasks:
                    channel_status_counts[task.status.value] += 1
                
                response_lines = [
                    f"**📋 Channel Task Status**",
                    f"Channel: <#{channel_id}>",
                    f"Total tasks: {total_tasks}",
                    f""
                ]
                
                # Add status summary
                status_emojis = {"scheduled": "⏰", "running": "🔄", "completed": "✅", "failed": "❌", "cancelled": "🛑"}
                for status, count in channel_status_counts.items():
                    if count > 0:
                        emoji = status_emojis.get(status, "📋")
                        response_lines.append(f"{emoji} {status.title()}: {count}")
                
                response_lines.append("")
                response_lines.append("**📋 Tasks by Alert:**")
                
                for alert_id, summary in task_summary.items():
                    alert_line = f"• {summary['alert_name']} (ID: {alert_id}):"
                    status_parts = []
                    for status, count in summary.items():
                        if status != "alert_name" and count > 0:
                            emoji = status_emojis.get(status, "📋")
                            status_parts.append(f"{emoji}{count}")
                    
                    if status_parts:
                        alert_line += " " + " ".join(status_parts)
                    else:
                        alert_line += " No active tasks"
                    
                    response_lines.append(alert_line)

            # Use pagination for channels with many alerts
            if len(response_lines) > 15:
                await self._send_paginated_response(ctx, response_lines, "Channel Task Status")
            else:
                response = "\n".join(response_lines)
                await ctx.respond(response, flags=hikari.MessageFlag.EPHEMERAL)

            info(f"Channel status: Provided status for channel {channel_id} to {author_info}. Total tasks: {len(channel_tasks) if channel_tasks else 0}")

        @self.bot.command
        @lightbulb.command("taskhelp", "Shows available task management commands.")
        @lightbulb.implements(lightbulb.SlashCommand)
        async def task_help(ctx: lightbulb.Context) -> None:
            help_text = """**📋 Task Management Commands**

**Individual Alert Control:**
• `/checkalert [alert]` - Manually trigger check for specific alert
• `/interruptalert [alert]` - Cancel running checks for specific alert  
• `/stopalertcheck [alert]` - Remove scheduled (not yet running) checks

**Channel Control:**
• `/interruptchannel` - Cancel ALL running checks in this channel
• `/channelstatus` - Show task status for this channel only

**System-Wide Control:**
• `/taskstatus` - Show status of all running tasks across all channels

**Discord Logging:**
• `/enablelogs` - Enable real-time log streaming to this channel
• `/disablelogs` - Disable Discord log streaming
• `/logstatus` - Check Discord logging status and configuration
• `/flushlogs` - Manually flush log buffer to Discord
• `/testlogs` - Send test logs to verify logging setup

**💡 Tips:**
- Use `/channelstatus` to see what's running in your channel
- Use `/interruptchannel` for emergency stops in busy channels
- Use `/enablelogs` to monitor bot activity in real-time
- Tasks cleanup automatically when they finish
- Cancellation is cooperative - tasks stop at next await point"""

            await ctx.respond(help_text, flags=hikari.MessageFlag.EPHEMERAL)