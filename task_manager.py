import asyncio
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from logging import info
import traceback

class TaskStatus(Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class TaskInfo:
    id: str
    alert_id: int
    alert_name: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    checkers: List[str] = field(default_factory=list)
    asyncio_tasks: List[asyncio.Task] = field(default_factory=list)
    
    @property
    def duration(self) -> Optional[float]:
        """Returns task duration in seconds if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    @property
    def age(self) -> float:
        """Returns how long ago the task was created in seconds."""
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, TaskInfo] = {}
        self.scheduler = None
        self.checker_function = None
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def initialize(self, scheduler, checker_function):
        """Initialize with scheduler and checker function references."""
        self.scheduler = scheduler
        self.checker_function = checker_function
        
        # Start cleanup task
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            info("TaskManager: Started periodic cleanup task")
    
    async def _periodic_cleanup(self):
        """Periodically clean up old completed/failed tasks."""
        while True:
            try:
                await asyncio.sleep(300)  # Cleanup every 5 minutes
                self._cleanup_old_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                info(f"TaskManager cleanup error: {e}")
    
    def _cleanup_old_tasks(self):
        """Remove tasks older than 30 minutes that are completed/failed."""
        current_time = datetime.now(timezone.utc)
        to_remove = []
        
        for task_id, task_info in self.tasks.items():
            if task_info.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                if (current_time - task_info.created_at).total_seconds() > 1800:  # 30 minutes
                    to_remove.append(task_id)
        
        for task_id in to_remove:
            del self.tasks[task_id]
            
        if to_remove:
            info(f"TaskManager: Cleaned up {len(to_remove)} old tasks")
    
    def schedule_alert_check(self, alert_id: int, alert_name: str) -> str:
        """Schedule an alert check and return task ID. Returns None if deduplication prevents scheduling."""
        # Task deduplication: Check for existing active tasks for this alert
        existing_tasks = self.get_tasks_by_alert(alert_id)
        active_tasks = [task for task in existing_tasks if task.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]]
        
        if active_tasks:
            info(f"TaskManager: Skipping duplicate schedule for alert {alert_id} '{alert_name}' - {len(active_tasks)} active task(s) already exist: {[t.id for t in active_tasks]}")
            return None
        
        task_id = f"alert_{alert_id}_{uuid.uuid4().hex[:8]}"
        
        task_info = TaskInfo(
            id=task_id,
            alert_id=alert_id,
            alert_name=alert_name,
            status=TaskStatus.SCHEDULED,
            created_at=datetime.now(timezone.utc)
        )
        
        self.tasks[task_id] = task_info
        
        # Schedule with APScheduler
        try:
            self.scheduler.add_job(
                self._execute_alert_check,
                args=[task_id],
                trigger='date',
                id=task_id,
                replace_existing=False,
                misfire_grace_time=60
            )
            info(f"TaskManager: Scheduled alert check {task_id} for '{alert_name}' (ID: {alert_id})")
            return task_id
        except Exception as e:
            task_info.status = TaskStatus.FAILED
            task_info.error_message = f"Scheduling failed: {e}"
            info(f"TaskManager: Failed to schedule {task_id}: {e}")
            return task_id
    
    async def _execute_alert_check(self, task_id: str):
        """Execute the actual alert check."""
        if task_id not in self.tasks:
            info(f"TaskManager: Task {task_id} not found for execution")
            return
        
        task_info = self.tasks[task_id]
        task_info.status = TaskStatus.RUNNING
        task_info.started_at = datetime.now(timezone.utc)
        
        # Capture the current asyncio task for cancellation tracking
        current_task = asyncio.current_task()
        if current_task:
            task_info.asyncio_tasks.append(current_task)
            info(f"TaskManager: Tracking asyncio task {current_task.get_name()} for {task_id}")
        
        info(f"TaskManager: Starting execution of {task_id} for alert '{task_info.alert_name}' (ID: {task_info.alert_id})")
        
        try:
            # Call the original checker function
            await self.checker_function(task_info.alert_id)
            
            task_info.status = TaskStatus.COMPLETED
            task_info.completed_at = datetime.now(timezone.utc)
            info(f"TaskManager: Completed {task_id} for alert '{task_info.alert_name}' in {task_info.duration:.2f}s")
            
        except asyncio.CancelledError:
            task_info.status = TaskStatus.CANCELLED
            task_info.completed_at = datetime.now(timezone.utc)
            info(f"TaskManager: Cancelled {task_id} for alert '{task_info.alert_name}'")
            raise  # Re-raise to ensure proper cancellation propagation
        except Exception as e:
            task_info.status = TaskStatus.FAILED
            task_info.completed_at = datetime.now(timezone.utc)
            task_info.error_message = str(e)
            info(f"TaskManager: Failed {task_id} for alert '{task_info.alert_name}': {e}")
    
    def cancel_tasks_for_alert(self, alert_id: int) -> int:
        """Cancel all scheduled/running tasks for a specific alert."""
        cancelled_count = 0
        
        for task_info in self.tasks.values():
            if task_info.alert_id == alert_id and task_info.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]:
                if self._cancel_task(task_info):
                    cancelled_count += 1
        
        return cancelled_count
    
    def cancel_tasks_for_channel(self, channel_id: int, alert_ids: List[int]) -> int:
        """Cancel all tasks for alerts in a specific channel."""
        cancelled_count = 0
        
        for task_info in self.tasks.values():
            if task_info.alert_id in alert_ids and task_info.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]:
                if self._cancel_task(task_info):
                    cancelled_count += 1
        
        return cancelled_count
    
    def _cancel_task(self, task_info: TaskInfo) -> bool:
        """Cancel a specific task."""
        try:
            cancelled_something = False
            
            # Remove from scheduler if scheduled
            if task_info.status == TaskStatus.SCHEDULED:
                try:
                    self.scheduler.remove_job(task_info.id)
                    cancelled_something = True
                    info(f"TaskManager: Removed scheduled job {task_info.id}")
                except:
                    pass  # Job might have already started or doesn't exist
            
            # Cancel asyncio tasks if running
            asyncio_cancelled_count = 0
            for asyncio_task in task_info.asyncio_tasks:
                if not asyncio_task.done():
                    asyncio_task.cancel()
                    asyncio_cancelled_count += 1
                    cancelled_something = True
                    info(f"TaskManager: Cancelled asyncio task {asyncio_task.get_name()} for {task_info.id}")
            
            if asyncio_cancelled_count > 0:
                info(f"TaskManager: Cancelled {asyncio_cancelled_count} asyncio task(s) for {task_info.id}")
            
            # If task is running but we have no asyncio tasks tracked, try to find and cancel it
            if task_info.status == TaskStatus.RUNNING and not task_info.asyncio_tasks:
                # Look for running tasks that might be this one
                all_tasks = [task for task in asyncio.all_tasks() if not task.done()]
                for task in all_tasks:
                    task_name = task.get_name()
                    # Check if this task name suggests it's related to our alert
                    if (task_name.startswith('Task-') and 
                        f"alert_{task_info.alert_id}_" in task_info.id):
                        # This might be our task, try to cancel it
                        task.cancel()
                        cancelled_something = True
                        info(f"TaskManager: Found and cancelled potential orphaned task {task_name} for {task_info.id}")
                        break
            
            if cancelled_something:
                task_info.status = TaskStatus.CANCELLED
                task_info.completed_at = datetime.now(timezone.utc)
                info(f"TaskManager: Successfully marked task {task_info.id} as cancelled")
                return True
            else:
                info(f"TaskManager: No cancellable components found for task {task_info.id}")
                return False
            
        except Exception as e:
            info(f"TaskManager: Error cancelling task {task_info.id}: {e}")
            return False
    
    async def cancel_tasks_for_alert_async(self, alert_id: int) -> int:
        """Cancel all scheduled/running tasks for a specific alert with async waiting."""
        cancelled_count = 0
        tasks_to_wait_for = []
        
        for task_info in self.tasks.values():
            if task_info.alert_id == alert_id and task_info.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]:
                if self._cancel_task(task_info):
                    cancelled_count += 1
                    # Collect asyncio tasks to wait for
                    for asyncio_task in task_info.asyncio_tasks:
                        if not asyncio_task.done():
                            tasks_to_wait_for.append(asyncio_task)
        
        # Wait for cancelled tasks to actually stop
        if tasks_to_wait_for:
            info(f"TaskManager: Waiting for {len(tasks_to_wait_for)} cancelled task(s) to complete for alert {alert_id}")
            try:
                done, pending = await asyncio.wait(tasks_to_wait_for, timeout=5.0, return_when=asyncio.ALL_COMPLETED)
                if pending:
                    info(f"TaskManager: {len(pending)} task(s) still pending after cancellation timeout for alert {alert_id}")
                else:
                    info(f"TaskManager: All cancelled tasks completed successfully for alert {alert_id}")
            except Exception as e:
                info(f"TaskManager: Error waiting for cancelled tasks for alert {alert_id}: {e}")
        
        return cancelled_count
    
    async def cancel_tasks_for_channel_async(self, channel_id: int, alert_ids: List[int]) -> int:
        """Cancel all tasks for alerts in a specific channel with async waiting."""
        cancelled_count = 0
        tasks_to_wait_for = []
        
        for task_info in self.tasks.values():
            if task_info.alert_id in alert_ids and task_info.status in [TaskStatus.SCHEDULED, TaskStatus.RUNNING]:
                if self._cancel_task(task_info):
                    cancelled_count += 1
                    # Collect asyncio tasks to wait for
                    for asyncio_task in task_info.asyncio_tasks:
                        if not asyncio_task.done():
                            tasks_to_wait_for.append(asyncio_task)
        
        # Wait for cancelled tasks to actually stop
        if tasks_to_wait_for:
            info(f"TaskManager: Waiting for {len(tasks_to_wait_for)} cancelled task(s) to complete for channel {channel_id}")
            try:
                done, pending = await asyncio.wait(tasks_to_wait_for, timeout=5.0, return_when=asyncio.ALL_COMPLETED)
                if pending:
                    info(f"TaskManager: {len(pending)} task(s) still pending after cancellation timeout for channel {channel_id}")
                else:
                    info(f"TaskManager: All cancelled tasks completed successfully for channel {channel_id}")
            except Exception as e:
                info(f"TaskManager: Error waiting for cancelled tasks for channel {channel_id}: {e}")
        
        return cancelled_count
    
    def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """Get status of a specific task."""
        return self.tasks.get(task_id)
    
    def get_tasks_by_status(self, status: TaskStatus) -> List[TaskInfo]:
        """Get all tasks with a specific status."""
        return [task for task in self.tasks.values() if task.status == status]
    
    def get_tasks_by_alert(self, alert_id: int) -> List[TaskInfo]:
        """Get all tasks for a specific alert."""
        return [task for task in self.tasks.values() if task.alert_id == alert_id]
    
    def get_tasks_by_alerts(self, alert_ids: List[int]) -> List[TaskInfo]:
        """Get all tasks for multiple alerts (for channel status)."""
        return [task for task in self.tasks.values() if task.alert_id in alert_ids]
    
    def get_all_tasks(self) -> List[TaskInfo]:
        """Get all tracked tasks."""
        return list(self.tasks.values())
    
    def get_summary(self) -> Dict[str, int]:
        """Get a summary count of tasks by status."""
        summary = {status.value: 0 for status in TaskStatus}
        for task in self.tasks.values():
            summary[task.status.value] += 1
        return summary
    
    def get_scheduler_jobs_info(self) -> Dict[str, Any]:
        """Get information about scheduler jobs."""
        if not self.scheduler:
            return {"error": "Scheduler not available"}
        
        try:
            jobs = self.scheduler.get_jobs()
            job_info = {
                "total_jobs": len(jobs),
                "scheduler_running": self.scheduler.running,
                "jobs": []
            }
            
            for job in jobs:
                # Check if job is paused by seeing if next_run_time is None for a recurring job
                is_paused = (job.next_run_time is None and 
                           hasattr(job.trigger, 'interval') and 
                           job.trigger.interval is not None)
                
                job_data = {
                    "id": job.id,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "function": getattr(job.func, '__name__', str(job.func)),
                    "paused": is_paused
                }
                job_info["jobs"].append(job_data)
            
            return job_info
            
        except Exception as e:
            return {"error": f"Failed to get scheduler info: {e}"}

# Global task manager instance
task_manager = TaskManager()

def get_task_manager() -> TaskManager:
    """Get the global task manager instance."""
    return task_manager

def setup_task_manager(scheduler, checker_function):
    """Initialize the task manager with scheduler and checker function."""
    task_manager.initialize(scheduler, checker_function)
    info("TaskManager: Initialized with scheduler and checker function") 