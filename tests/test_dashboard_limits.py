"""Who a request comes from behind reverse proxies, and the bounded counting of failed sign-ins."""
import ipaddress

import pytest

from dashboard_limits import (FailureLimiter, client_address, forwarded_proto, parse_proxies, visitor_key)

PROXIES = parse_proxies("172.18.0.0/16, 10.0.0.5")
ip = ipaddress.ip_address


def test_the_setting_takes_addresses_and_ranges_and_refuses_anything_else():
    assert [str(network) for network in PROXIES] == ["172.18.0.0/16", "10.0.0.5/32"]
    assert parse_proxies("") == () and parse_proxies(" , ") == ()
    assert [str(network) for network in parse_proxies("fd00::/8,172.18.0.7/16")] == ["fd00::/8", "172.18.0.0/16"]
    with pytest.raises(ValueError, match="'nginx' is neither"):
        parse_proxies("172.18.0.0/16, nginx")


def test_an_untrusted_peer_is_the_visitor_whatever_it_forwards():
    assert client_address("198.51.100.8", ["1.2.3.4"], PROXIES) == ip("198.51.100.8")
    assert client_address("198.51.100.8", [], ()) == ip("198.51.100.8")


def test_through_trusted_proxies_the_rightmost_untrusted_entry_is_the_visitor():
    # nginx replaces the header with Cloudflare's visitor address.
    assert client_address("172.18.0.3", ["203.0.113.7"], PROXIES) == ip("203.0.113.7")
    # traefik appends; whatever the visitor wrote on the left does not count.
    assert client_address("172.18.0.4", ["6.6.6.6, 203.0.113.7, 172.18.0.3"], PROXIES) == ip("203.0.113.7")
    assert client_address("172.18.0.4", ["6.6.6.6", "203.0.113.7:51000"], PROXIES) == ip("203.0.113.7")
    assert client_address("172.18.0.4", ["[2001:db8::7]:443"], PROXIES) == ip("2001:db8::7")
    # No header, a broken entry, or only proxies: the last known address.
    assert client_address("172.18.0.4", [], PROXIES) == ip("172.18.0.4")
    assert client_address("172.18.0.4", ["unknown"], PROXIES) == ip("172.18.0.4")
    assert client_address("172.18.0.4", ["172.18.0.9, 10.0.0.5"], PROXIES) == ip("172.18.0.9")


def test_only_trusted_proxies_say_whether_the_browser_used_https():
    assert forwarded_proto("172.18.0.3", "https", PROXIES) == "https"
    assert forwarded_proto("172.18.0.3", "HTTPS, http", PROXIES) == "https"
    assert forwarded_proto("198.51.100.8", "https", PROXIES) is None
    assert forwarded_proto("172.18.0.3", "gopher", PROXIES) is None


def test_visitors_are_counted_per_ipv4_address_and_per_ipv6_64():
    assert visitor_key(ip("203.0.113.7")) == "203.0.113.7"
    assert visitor_key(ip("2001:db8:1:2:aaaa::1")) == visitor_key(ip("2001:db8:1:2::9")) == "2001:db8:1:2::/64"
    assert visitor_key(ip("2001:db8:1:3::1")) == "2001:db8:1:3::/64"
    # An IPv4 visitor written as IPv6 is the same visitor.
    assert visitor_key(client_address("::ffff:203.0.113.7", [], ())) == "203.0.113.7"
    assert visitor_key(None) == "unknown"


def test_failures_expire_after_a_minute_and_the_table_stays_bounded():
    now = [1000.0]
    limiter = FailureLimiter(3, max_keys=2, clock=lambda: now[0])
    for _ in range(3):
        limiter.record("a")
    assert limiter.blocked("a") and not limiter.blocked("b")
    now[0] += 61
    assert not limiter.blocked("a") and len(limiter) == 0
    for key in ("a", "b", "c"):
        limiter.record(key)
    # The visitor whose last failure is oldest is forgotten first.
    assert list(limiter.failures) == ["b", "c"]
    for _ in range(10):
        limiter.record("c")
    assert len(limiter.failures["c"]) == 3
