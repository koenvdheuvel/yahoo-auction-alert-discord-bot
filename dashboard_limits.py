"""Who a request comes from, and how many sign-ins failed for them in the last minute.

Behind a reverse proxy every request comes from the proxy's address. Only the proxies listed in
DASHBOARD_TRUSTED_PROXIES may say who the visitor is (X-Forwarded-For) and whether the browser
used https (X-Forwarded-Proto). From anyone else those headers are ignored, because a visitor can
send them too.
"""
from collections import OrderedDict, deque
import ipaddress
import time


# A visitor whose sign-ins failed this often in the last minute is refused for the rest of it.
VISITOR_FAILURES_PER_MINUTE = 10
# Failed sign-ins that cost Discord API calls, for everyone together: a code Discord did not
# accept, or a membership check that found nothing. The bot shares its address with production,
# and Discord blocks addresses that make many failing calls.
DISCORD_FAILURES_PER_MINUTE = 60
WINDOW_SECONDS = 60
# Visitors with recent failures that are remembered. Past this, the one whose last failure is
# oldest is forgotten first.
MAX_VISITORS = 4096


def parse_proxies(value, name="DASHBOARD_TRUSTED_PROXIES"):
    """Comma-separated addresses or CIDR ranges, such as "172.18.0.0/16, 10.0.0.5", as networks."""
    networks = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ValueError(f"{name} must be comma-separated addresses or CIDR ranges, such as "
                             f"172.18.0.0/16; {part!r} is neither") from None
    return tuple(networks)


def _address(text):
    """An IP address from a header entry or a socket peer, without a port; None when it is not one."""
    text = (text or "").strip()
    if text.startswith("["):
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:
        # IPv4 with a port. IPv6 has more than one colon.
        text = text.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address


def _trusted(address, proxies):
    return address is not None and any(address.version == network.version and address in network
                                       for network in proxies)


def client_address(peer, forwarded_for, proxies):
    """The visitor's address.

    It is the TCP peer, unless the peer is a trusted proxy. Then it is the rightmost
    X-Forwarded-For entry that is not a trusted proxy itself: each proxy adds the address it got
    the request from at the end, so entries further left could have been written by the visitor.
    forwarded_for holds every X-Forwarded-For header of the request.
    """
    address = _address(peer)
    if not _trusted(address, proxies):
        return address
    entries = [entry for header in forwarded_for for entry in header.split(",") if entry.strip()]
    for entry in reversed(entries):
        found = _address(entry)
        if found is None:
            # Not an address: the proxy that sent it is the last one known.
            return address
        if not _trusted(found, proxies):
            return found
    # Every entry is a trusted proxy too: the request started inside the trusted network.
    return _address(entries[0]) if entries else address


def forwarded_proto(peer, value, proxies):
    """The browser's scheme from X-Forwarded-Proto, only when a trusted proxy sent it; else None."""
    if not _trusted(_address(peer), proxies):
        return None
    scheme = (value or "").split(",")[0].strip().lower()
    return scheme if scheme in {"http", "https"} else None


def visitor_key(address):
    """What failures are counted under. IPv6 visitors usually hold a whole /64, so it counts as one."""
    if address is None:
        return "unknown"
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


class FailureLimiter:
    """Failures per key within the last WINDOW_SECONDS, for at most max_keys keys."""

    def __init__(self, limit, *, window=WINDOW_SECONDS, max_keys=MAX_VISITORS, clock=time.monotonic):
        self.limit, self.window, self.max_keys, self.clock = limit, window, max_keys, clock
        # Key to the times of its failures, ordered by each key's latest failure, oldest first.
        self.failures = OrderedDict()

    def _forget_old(self, now):
        while self.failures:
            key, times = next(iter(self.failures.items()))
            if times[-1] > now - self.window:
                break
            del self.failures[key]

    def blocked(self, key):
        now = self.clock()
        self._forget_old(now)
        times = self.failures.get(key)
        if not times:
            return False
        while times and times[0] <= now - self.window:
            times.popleft()
        return len(times) >= self.limit

    def record(self, key):
        now = self.clock()
        self._forget_old(now)
        times = self.failures.pop(key, None) or deque(maxlen=self.limit)
        times.append(now)
        self.failures[key] = times
        while len(self.failures) > self.max_keys:
            self.failures.popitem(last=False)

    def __len__(self):
        """How many failures are remembered, over every key."""
        self._forget_old(self.clock())
        return sum(len(times) for times in self.failures.values())
