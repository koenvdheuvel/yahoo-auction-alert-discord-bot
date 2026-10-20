"""Explicit registration and native application dependency injection."""
import lightbulb

from commands.alerts import AlertsCommand
from commands.allalerts import AllAlertsCommand
from commands.base import CommandServices
from commands.cleanup import CleanupCommand
from commands.filters import filters_group
from commands.marketplaces import marketplaces_group
from commands.reacttocleanup import ReactToCleanupCommand
from commands.register import RegisterCommand
from commands.unregister import UnregisterCommand


COMMANDS = (
    AlertsCommand, AllAlertsCommand, CleanupCommand, filters_group, marketplaces_group,
    ReactToCleanupCommand, RegisterCommand, UnregisterCommand,
)


def register_commands(client, bot, repository, enabled_sources):
    services = CommandServices(bot, repository, enabled_sources=tuple(enabled_sources))
    client.di.registry_for(lightbulb.di.Contexts.DEFAULT).register_value(
        CommandServices, services, teardown=CommandServices.close,
    )
    for command in COMMANDS:
        client.register(command)
    return services
