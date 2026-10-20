"""The marketplaces the bot can search. Every list of supported sources comes from here.

A source ID is stored with each listing, in rulesets and in each search's marketplace
choices, so an ID never changes. This module does no I/O: filtering imports it.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Marketplace:
    source: str
    # As Discord replies and the dashboard name it.
    name: str
    # The edge of the listing's Discord post.
    color: int
    # The setting that turns the marketplace off for the whole bot; on by default.
    setting: str


MARKETPLACES = (
    Marketplace("yahooauction", "Yahoo Auctions", 0xFFA500, "ENABLE_YAHOO_AUCTION"),
    Marketplace("mercari", "Mercari", 0xFF0000, "ENABLE_MERCARI"),
    Marketplace("surugaya", "Surugaya", 0x0000FF, "ENABLE_SURUGAYA"),
    Marketplace("rakuma", "Rakuma", 0xE4007F, "ENABLE_RAKUMA"),
)
SOURCES = frozenset(marketplace.source for marketplace in MARKETPLACES)
# Source ID to marketplace, in the order above.
BY_SOURCE = {marketplace.source: marketplace for marketplace in MARKETPLACES}
