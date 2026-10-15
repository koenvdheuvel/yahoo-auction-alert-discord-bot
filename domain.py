"""Marketplace facts and deterministic notification policy, independent of I/O."""
from dataclasses import asdict, dataclass
from datetime import datetime
import re

import regex

FILTER_TIMEOUT_SECONDS = 0.05


class FilterTimeout(TimeoutError):
    def __init__(self, filter_id):
        self.filter_id = filter_id
        super().__init__(f"Filter {filter_id} exceeded its evaluation deadline")


@dataclass(frozen=True)
class Listing:
    id: str
    source: str
    title: str
    stock: int
    price: int
    buyout_price: int = 0
    image_url: str = ""
    url: str = ""
    end_time: datetime | None = None

    def payload(self):
        values = asdict(self)
        values["end_time"] = self.end_time.isoformat() if self.end_time else None
        return values


def changes(previous, current, threshold=500):
    """Preserve existing stock rule and consecutive-observation price baseline."""
    result = []
    if previous.stock != current.stock and current.stock > 1:
        result.append(f"Stock changed from {previous.stock} to {current.stock}")
    if previous.price - current.price > threshold:
        result.append(f"Price changed from ¥{previous.price} to ¥{current.price}")
    if abs(previous.buyout_price - current.buyout_price) > threshold:
        result.append(f"Buyout price changed from ¥{previous.buyout_price} to ¥{current.buyout_price}")
    return result


@dataclass(frozen=True)
class FilterRule:
    id: int
    method: str
    policy: str
    value: str

    def matcher(self):
        if self.policy not in {"blacklist", "whitelist"}:
            raise ValueError("Unknown filter policy")
        if self.method == "text":
            return lambda title: self.value in title
        if self.method == "regex":
            # Keep stdlib syntax/validation, but bound matching with the timeout-capable engine.
            re.compile(self.value)
            pattern = regex.compile(self.value, regex.VERSION0)
            return lambda title: bool(pattern.search(title, timeout=FILTER_TIMEOUT_SECONDS))
        raise ValueError("Unknown filter method")


class FilterPolicy:
    """Blacklist vetoes; any whitelist match admits; no whitelist admits by default."""
    def __init__(self, rules):
        self.rules = [(rule, rule.matcher()) for rule in rules]
        self.has_regex = any(rule.method == "regex" for rule, _ in self.rules)

    def evaluate(self, title):
        matching = []
        for rule, match in self.rules:
            try:
                if match(title):
                    matching.append(rule)
            except TimeoutError as error:
                raise FilterTimeout(rule.id) from error
        blocked = any(rule.policy == "blacklist" for rule in matching)
        whitelisted = any(rule.policy == "whitelist" for rule in matching)
        has_whitelist = any(rule.policy == "whitelist" for rule, _ in self.rules)
        return not blocked and (not has_whitelist or whitelisted), [rule.id for rule in matching]
