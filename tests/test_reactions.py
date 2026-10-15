"""Historical message identity and repeated reactions must remain safe."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import hikari

from processors.hikari_event import HikariEventProcessor
from strategies.emoji_reactions.delete_message import DeleteMessageStrategy
from strategies.emoji_reactions.remove_notification import RemoveNotificationStrategy
from strategies.emoji_reactions.setup_notification import SetupNotificationStrategy


class Repository:
    def __init__(self):
        self.messages = {(10, 111): {"item_id": 5, "external_id": "old-post",
                                   "source": "yahoo", "channel_id": 10, "message_id": 111}}
        self.subscriptions = set()
        self.blacklist = set()
        self.deleted = set()

    async def lookup_message(self, channel_id, message_id):
        return self.messages.get((channel_id, message_id))

    async def subscribe(self, item_id, user_id):
        key = (item_id, user_id)
        created = key not in self.subscriptions
        self.subscriptions.add(key)
        return created

    async def unsubscribe(self, item_id, user_id):
        key = (item_id, user_id)
        existed = key in self.subscriptions
        self.subscriptions.discard(key)
        return existed

    async def blacklist_item(self, item_id, channel_id):
        self.blacklist.add((item_id, channel_id))

    async def mark_message_deleted(self, channel_id, message_id):
        self.deleted.add((channel_id, message_id))


def bot_with(repository):
    return SimpleNamespace(
        services=SimpleNamespace(repository=repository),
        rest=SimpleNamespace(
            fetch_message=AsyncMock(side_effect=AssertionError("Do not fetch arbitrary messages")),
            create_dm_channel=AsyncMock(return_value=SimpleNamespace(id=700)),
            create_message=AsyncMock(), delete_message=AsyncMock(),
        ),
    )


def reaction(**kwargs):
    return SimpleNamespace(**{
        "channel_id": 10, "message_id": 111, "guild_id": 100, "user_id": 600,
        "emoji_name": "🔔", **kwargs,
    })


class ReactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscribe_and_unsubscribe_are_idempotent_for_historical_posts(self):
        repository = Repository()
        bot = bot_with(repository)
        event = reaction()
        for _ in range(2):
            await SetupNotificationStrategy().execute(event, bot)
        self.assertEqual(repository.subscriptions, {(5, 600)})
        self.assertEqual(bot.rest.create_message.await_count, 1)
        for _ in range(2):
            await RemoveNotificationStrategy().execute(event, bot)
        self.assertEqual(repository.subscriptions, set())
        self.assertEqual(bot.rest.create_message.await_count, 2)
        bot.rest.fetch_message.assert_not_awaited()

    async def test_closed_dms_do_not_lose_subscription_or_unsubscription(self):
        repository = Repository()
        bot = bot_with(repository)
        bot.rest.create_dm_channel.side_effect = hikari.ForbiddenError(
            "https://discord.test", {}, "", message="Cannot send messages to this user", code=50007,
        )
        with self.assertLogs("strategies.emoji_reactions.base", level="WARNING"):
            await SetupNotificationStrategy().execute(reaction(), bot)
        self.assertEqual(repository.subscriptions, {(5, 600)})
        with self.assertLogs("strategies.emoji_reactions.base", level="WARNING"):
            await RemoveNotificationStrategy().execute(reaction(), bot)
        self.assertEqual(repository.subscriptions, set())

    async def test_untracked_messages_and_other_channels_are_ignored(self):
        repository = Repository()
        bot = bot_with(repository)
        for strategy in (SetupNotificationStrategy(), RemoveNotificationStrategy(), DeleteMessageStrategy()):
            await strategy.execute(reaction(message_id=999), bot)
            await strategy.execute(reaction(channel_id=20), bot)
        self.assertEqual(repository.subscriptions, set())
        self.assertEqual(repository.blacklist, set())
        bot.rest.create_dm_channel.assert_not_awaited()
        bot.rest.delete_message.assert_not_awaited()

    async def test_delete_race_marks_history_deleted_and_blacklists_only_current_channel(self):
        repository = Repository()
        bot = bot_with(repository)
        bot.rest.delete_message.side_effect = hikari.NotFoundError(
            "https://discord.test", {}, "", message="Unknown Message", code=10008,
        )
        for _ in range(2):
            await DeleteMessageStrategy().execute(reaction(), bot)
        self.assertEqual(repository.blacklist, {(5, 10)})
        self.assertEqual(repository.deleted, {(10, 111)})

    async def test_forbidden_delete_keeps_history_and_blacklist_for_retry(self):
        repository = Repository()
        bot = bot_with(repository)
        bot.rest.delete_message.side_effect = hikari.ForbiddenError(
            "https://discord.test", {}, "", message="Missing permissions", code=50013,
        )
        with self.assertLogs("strategies.emoji_reactions.delete_message", level="WARNING"):
            await DeleteMessageStrategy().execute(reaction(), bot)
        self.assertEqual(repository.blacklist, {(5, 10)})
        self.assertEqual(repository.deleted, set())

    async def test_processor_records_and_logs_handler_failure(self):
        event = reaction()
        processor = HikariEventProcessor()
        processor._handlers[type(event)] = SimpleNamespace(
            handle=AsyncMock(side_effect=RuntimeError("repository unavailable")),
        )
        counter = SimpleNamespace(inc=Mock())
        bot = SimpleNamespace(services=SimpleNamespace(runtime=SimpleNamespace(
            metrics=SimpleNamespace(reaction_errors=counter),
        )))
        with self.assertLogs("processors.hikari_event", level="ERROR") as captured:
            await processor.process_event(event, bot)
        counter.inc.assert_called_once_with()
        self.assertIn("repository unavailable", captured.output[0])
