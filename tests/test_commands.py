"""Native Lightbulb 3 registration, DI, permission and component regression tests."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import hikari
import lightbulb

from commands import register_commands
from commands.base import CommandServices, GuildOnlyError, PageMenu, paginate_lines
from commands.filters import filters_group
from channel_maintenance import add_cleanup_reactions


class History:
    def __init__(self, messages):
        self.messages = list(messages)
        self.requested_limit = None

    def limit(self, count):
        self.requested_limit = count
        self.messages = self.messages[:count]
        return self

    async def __aiter__(self):
        for message in self.messages:
            yield message


def post(message_id, author_id=500, message_type=hikari.MessageType.DEFAULT):
    return SimpleNamespace(id=message_id, author=SimpleNamespace(id=author_id),
                           type=message_type, interaction_metadata=None)


def make_interaction(name, options=None, guild_id=100, permissions=None):
    return SimpleNamespace(
        command_name=name, command_type=hikari.CommandType.SLASH,
        registered_guild_id=None, channel_id=10, guild_id=guild_id,
        user=SimpleNamespace(id=600), resolved=None, options=options or [],
        member=SimpleNamespace(permissions=permissions if permissions is not None
                               else hikari.Permissions.MANAGE_CHANNELS),
        create_initial_response=AsyncMock(),
        execute=AsyncMock(return_value=SimpleNamespace(id=700)),
        edit_initial_response=AsyncMock(), edit_message=AsyncMock(),
        fetch_initial_response=AsyncMock(),
    )


def option(name, value):
    option_type = hikari.OptionType.INTEGER if isinstance(value, int) else hikari.OptionType.STRING
    return hikari.CommandInteractionOption(name=name, type=option_type, value=value, options=None)


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repository = SimpleNamespace(
            register_alert=AsyncMock(return_value=True),
            unregister_alert=AsyncMock(return_value=False),
            list_alerts=AsyncMock(return_value=[]),
            list_filters=AsyncMock(return_value=[]),
            add_filter=AsyncMock(return_value=None),
            delete_filter=AsyncMock(return_value=False),
            mark_message_deleted=AsyncMock(), lookup_message=AsyncMock(return_value=None),
        )
        self.bot = hikari.GatewayBot("MTIzNDU2Nzg5MDEyMzQ1Njc4.test.test", logs=None, banner=None)
        self.client = lightbulb.client_from_app(self.bot, sync_commands=False)
        self.services = register_commands(self.client, self.bot, self.repository)
        self.errors = []

        @self.client.error_handler
        async def collect_error(error):
            self.errors.append(error)
            return True

        await self.client.start()  # Native builder resolution, with no Discord API calls.
        self.addAsyncCleanup(self.client.stop)
        self.addAsyncCleanup(self.services.close)

    async def invoke(self, name, *, guild_id=100, permissions=None, **values):
        root, *subcommand = name.split()
        leaves = [option(key, value) for key, value in values.items()]
        options = leaves if not subcommand else [hikari.CommandInteractionOption(
            name=subcommand[0], type=hikari.OptionType.SUB_COMMAND, value=None, options=leaves,
        )]
        interaction = make_interaction(root, options, guild_id, permissions)
        await self.client.handle_application_command_interaction(interaction, asyncio.Event())
        return interaction

    def fake_history(self, messages):
        history = History(messages)
        rest = SimpleNamespace(
            fetch_messages=Mock(return_value=history),
            delete_message=AsyncMock(), add_reaction=AsyncMock(),
        )
        self.services.bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=500))
        return history, rest

    async def test_native_sdk_builds_every_command_and_preserves_permissions_and_contexts(self):
        built = []
        for command in self.client.registered_commands:
            builder = await command.as_command_builder(
                self.client.default_locale, self.client.localization_provider,
            )
            built.append(builder)
            payload = builder.build(self.bot.entity_factory)
            self.assertEqual(payload["name"], builder.name)
            self.assertEqual(builder.context_types, [hikari.ApplicationContextType.GUILD])
            self.assertEqual(builder.integration_types, [hikari.ApplicationIntegrationType.GUILD_INSTALL])
        self.assertEqual({builder.name for builder in built}, {
            "alerts", "allalerts", "cleanup", "filters", "reacttocleanup", "register", "unregister",
        })
        managed = {builder.name: builder for builder in built
                   if builder.name not in ("alerts", "filters")}
        for builder in managed.values():
            self.assertEqual(builder.default_member_permissions, hikari.Permissions.MANAGE_CHANNELS)
        group = next(builder for builder in built if builder.name == "filters")
        self.assertEqual({child.name for child in group.options}, {"list", "get", "add", "delete"})
        add = next(child for child in group.options if child.name == "add")
        self.assertEqual([opt.name for opt in add.options], ["search_query", "method", "value", "type"])
        self.assertEqual([opt.is_required for opt in add.options], [True, True, True, False])
        self.assertTrue(all(mock.await_count == 0 for mock in vars(self.repository).values()))

    async def test_manage_permission_and_dm_checks_prevent_mutations_in_real_pipeline(self):
        operations = [
            ("register", {"search_query": "vinyl"}), ("unregister", {"search_query": "vinyl"}),
            ("cleanup", {}), ("reacttocleanup", {}), ("allalerts", {}),
            ("filters add", {"search_query": "vinyl", "method": "text", "value": "limited"}),
            ("filters delete", {"id": 99}),
        ]
        for name, values in operations:
            with self.subTest(command=name):
                denied = await self.invoke(name, permissions=hikari.Permissions.NONE, **values)
                self.assertIsInstance(self.errors[-1].causes[0],
                                      lightbulb.prefab.MissingRequiredPermission)
                denied.create_initial_response.assert_not_awaited()
                dm = await self.invoke(name, guild_id=None, **values)
                self.assertIsInstance(self.errors[-1].causes[0], GuildOnlyError)
                dm.create_initial_response.assert_not_awaited()
        self.assertTrue(all(mock.await_count == 0 for mock in vars(self.repository).values()))

    async def test_administrators_pass_native_management_check(self):
        interaction = await self.invoke(
            "register", permissions=hikari.Permissions.ADMINISTRATOR, search_query="vinyl",
        )
        self.assertEqual(self.errors, [])
        self.repository.register_alert.assert_awaited_once_with(10, "vinyl", guild_id=100)
        self.assertEqual(interaction.execute.await_count, 1)

    async def test_duplicate_registration_deferred_privately_and_returns_one_response(self):
        self.repository.register_alert.return_value = False
        interaction = await self.invoke("register", search_query="  vinyl  ")
        self.assertEqual(self.errors, [])
        self.repository.register_alert.assert_awaited_once_with(10, "vinyl", guild_id=100)
        self.assertEqual(interaction.execute.await_count, 1)
        self.assertIn("already exists", interaction.execute.await_args.args[0])
        self.assertEqual(interaction.create_initial_response.await_args.args[0],
                         hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
        self.assertEqual(interaction.create_initial_response.await_args.kwargs["flags"],
                         hikari.MessageFlag.EPHEMERAL)
        self.assertEqual(interaction.execute.await_args.kwargs["flags"], hikari.MessageFlag.EPHEMERAL)

    async def test_autocomplete_uses_native_context_di_and_current_channel(self):
        self.repository.list_alerts.return_value = [
            {"search_query": "VINYL"}, {"search_query": "book"},
        ]
        autocomplete = make_interaction("unregister")
        autocomplete.options = [hikari.AutocompleteInteractionOption(
            name="search_query", type=hikari.OptionType.STRING, value="vin", options=None,
            is_focused=True,
        )]
        autocomplete.create_response = AsyncMock()
        await self.client.handle_autocomplete_interaction(autocomplete, asyncio.Event())
        self.repository.list_alerts.assert_awaited_once_with(channel_id=10)
        autocomplete.create_response.assert_awaited_once()
        choices = autocomplete.create_response.await_args.args[0]
        self.assertEqual([(choice.name, choice.value) for choice in choices], [("VINYL", "VINYL")])

    async def test_unregister_and_allalerts_apply_channel_and_guild_scope(self):
        response = await self.invoke("unregister", search_query="vinyl")
        self.repository.unregister_alert.assert_awaited_once_with(10, "vinyl")
        self.assertIn("this channel", response.execute.await_args.args[0])
        await self.invoke("allalerts")
        self.repository.list_alerts.assert_awaited_once_with(channel_id=10, guild_id=100)

    async def test_filter_method_policy_and_optional_default_resolve_through_native_options(self):
        response = await self.invoke("filters add", search_query="vinyl", method="regex",
                                     value="limited", type="whitelist")
        self.assertEqual(self.errors, [])
        self.repository.add_filter.assert_awaited_once_with(10, "vinyl", "regex", "whitelist", "limited")
        self.assertIn("does not exist", response.execute.await_args.args[0])
        self.repository.add_filter.reset_mock()
        await self.invoke("filters add", search_query="vinyl", method="text", value="limited")
        self.repository.add_filter.assert_awaited_once_with(10, "vinyl", "text", "blacklist", "limited")

    async def test_filter_deletion_has_no_stale_choices_and_stays_in_channel(self):
        command = filters_group.subcommands["delete"]
        builder = await command.as_command_builder(
            self.client.default_locale, self.client.localization_provider,
        )
        self.assertIsNone(builder.options[0].choices)
        response = await self.invoke("filters delete", id=99)
        self.repository.delete_filter.assert_awaited_once_with(10, 99)
        self.assertIn("this channel", response.execute.await_args.args[0])

    async def test_cleanup_skips_interaction_metadata_and_human_messages(self):
        extra_response = post(5)
        extra_response.interaction_metadata = object()
        history, rest = self.fake_history([
            post(1, message_type=hikari.MessageType.CHAT_INPUT), extra_response,
            post(2, author_id=600), post(3), post(4),
        ])
        interaction = await self.invoke("cleanup", count=1)
        self.assertEqual(self.errors, [])
        self.assertEqual(history.requested_limit, 1000)
        rest.delete_message.assert_awaited_once_with(10, 3)
        self.repository.mark_message_deleted.assert_awaited_once_with(10, 3)
        self.assertEqual(interaction.create_initial_response.await_args.kwargs["flags"],
                         hikari.MessageFlag.EPHEMERAL)

    async def test_cleanup_rejects_unbounded_count_without_history_fetch(self):
        _, rest = self.fake_history([])
        for count in (-1, 0, 101):
            response = await self.invoke("cleanup", count=count)
            self.assertIn("Count must", response.execute.await_args.args[0])
        rest.fetch_messages.assert_not_called()
        self.assertEqual(self.errors, [])

    async def test_cleanup_does_not_scan_unbounded_history(self):
        _, rest = self.fake_history([post(i, author_id=600) for i in range(1000)] + [post(1001)])
        await self.invoke("cleanup", count=1)
        rest.delete_message.assert_not_awaited()

    async def test_cleanup_reactions_only_target_tracked_posts(self):
        self.repository.lookup_message.side_effect = (
            lambda channel, message: {"item_id": 1} if message == 3 else None
        )
        history, rest = self.fake_history([post(1), post(2, author_id=600), post(3)])
        added = await add_cleanup_reactions(rest, self.repository, 500, 10)
        self.assertEqual(added, 1)
        rest.add_reaction.assert_awaited_once_with(10, 3, "🗑️")
        self.assertEqual(history.requested_limit, 1000)

    async def test_multpage_output_uses_native_buttons_and_cancels_on_service_close(self):
        self.repository.list_alerts.return_value = [
            {"search_query": "x" * 100} for _ in range(30)
        ]
        response = await self.invoke("alerts")
        self.assertEqual(self.errors, [])
        menu = response.execute.await_args.kwargs["components"]
        self.assertIsInstance(menu, PageMenu)
        self.assertLessEqual(len(menu.content), 2000)
        self.assertTrue(menu.previous.disabled)
        self.assertFalse(menu.next.disabled)
        await asyncio.sleep(0)
        self.assertEqual(len(self.client._attached_menus), 1)
        await self.services.close()
        self.assertEqual(self.services.pagination_tasks, set())
        self.assertEqual(len(self.client._attached_menus), 0)
        self.assertTrue(menu.next.disabled)

    async def test_native_menu_restricts_author_and_edits_page_without_mentions(self):
        menu = PageMenu(["one", "two"], owner_id=600)
        row, _ = menu[0].build()
        self.assertEqual(len(row["components"]), 2)
        self.assertEqual([button["label"] for button in row["components"]], ["Previous", "Next"])
        interaction = make_interaction("ignored")
        ctx = lightbulb.components.MenuContext(
            self.client, menu, interaction, menu.next, None, asyncio.Event(), asyncio.Event(),
        )
        self.assertTrue(await menu.predicate(ctx))
        await menu.next.callback(ctx)
        self.assertEqual(menu.index, 1)
        self.assertTrue(menu.next.disabled)
        self.assertFalse(menu.previous.disabled)
        self.assertEqual(interaction.create_initial_response.await_args.args[0],
                         hikari.ResponseType.MESSAGE_UPDATE)
        self.assertFalse(interaction.create_initial_response.await_args.kwargs["mentions_everyone"])

        unauthorized = make_interaction("ignored")
        unauthorized.user.id = 601
        outsider = lightbulb.components.MenuContext(
            self.client, menu, unauthorized, menu.previous, None, asyncio.Event(), asyncio.Event(),
        )
        self.assertFalse(await menu.predicate(outsider))
        self.assertEqual(menu.index, 1)
        self.assertEqual(unauthorized.create_initial_response.await_args.kwargs["flags"],
                         hikari.MessageFlag.EPHEMERAL)

    async def test_pagination_expires_and_removes_handlers(self):
        self.repository.list_alerts.return_value = [{"search_query": "x" * 100} for _ in range(30)]
        with patch("commands.base.PAGINATION_TIMEOUT", 0.01):
            response = await self.invoke("alerts")
            tasks = tuple(self.services.pagination_tasks)
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        menu = response.execute.await_args.kwargs["components"]
        self.assertTrue(menu.previous.disabled)
        self.assertTrue(menu.next.disabled)
        self.assertEqual(len(self.client._attached_menus), 0)

    async def test_output_chunks_long_legacy_values_and_never_enables_mentions(self):
        pages = paginate_lines(["@everyone " + "x" * 4000])
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 1800 for page in pages))
        self.assertNotIn("@everyone", "".join(pages))
        interaction = await self.invoke("alerts")
        self.assertFalse(interaction.execute.await_args.kwargs["mentions_everyone"])

    async def test_native_dependency_injection_has_no_bot_data_store(self):
        await self.invoke("alerts")
        async with self.client.di.enter_context(lightbulb.di.Contexts.DEFAULT) as container:
            services = await container.get(CommandServices)
            self.assertIs(services, self.services)
            self.assertIs(services.repository, self.repository)
        self.assertFalse(hasattr(self.bot, "d"))

    async def test_native_dependency_teardown_cancels_and_settles_pagination_tasks(self):
        self.repository.list_alerts.return_value = [{"search_query": "x" * 100} for _ in range(30)]
        await self.invoke("alerts")
        tasks = tuple(self.services.pagination_tasks)
        await asyncio.sleep(0)
        self.assertEqual(len(self.client._attached_menus), 1)
        await self.client.stop()
        self.assertEqual(self.services.pagination_tasks, set())
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(len(self.client._attached_menus), 0)
