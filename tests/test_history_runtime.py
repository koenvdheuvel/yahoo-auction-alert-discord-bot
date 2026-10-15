"""Bounded archive cleanup catches up without postponing database statistics."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from test_runtime import build_runtime


def test_retention_backlog_continues_on_statistics_ticks_and_then_waits():
    runtime = build_runtime(AsyncMock())
    runtime.repository.prune_candidates = AsyncMock(side_effect=[
        {"has_more": True}, {"has_more": True}, {"has_more": False},
    ])
    runtime.repository.stats = AsyncMock(wraps=runtime.repository.stats)
    ticks = 0

    async def advance_tick(delay):
        nonlocal ticks
        ticks += 1
        if ticks == 4:
            raise asyncio.CancelledError()

    async def run():
        with patch("runtime.asyncio.sleep", advance_tick):
            with pytest.raises(asyncio.CancelledError):
                await runtime.watch_stats()

    asyncio.run(run())
    assert runtime.repository.prune_candidates.await_count == 3
    runtime.repository.prune_candidates.assert_awaited_with(
        runtime.settings.history_retention_days, runtime.settings.history_max_rows)
    assert runtime.repository.stats.await_count == 4
    assert runtime.health.repository_available
