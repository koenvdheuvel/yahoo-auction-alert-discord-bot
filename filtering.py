"""Deterministic, explained eligibility decisions without storage or delivery I/O."""
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import islice
import re
import time

import regex

from domain import FILTER_TIMEOUT_SECONDS, FilterPolicy, FilterRule, FilterTimeout, Listing
from marketplaces import SOURCES
from normalization import NORMALIZATION_VERSION, normalize_title, validate_options


MAX_GROUPS = 20
MAX_TERMS_PER_GROUP = 20
MAX_TERMS = 100
MAX_REGEX_TERMS = 20
MAX_LEGACY_RULES = 50
EVALUATION_BUDGET_SECONDS = 0.25


class RulesetError(ValueError):
    """An invalid ruleset. `path` names the field, for example "groups.1.terms.0"."""

    def __init__(self, message, path=""):
        super().__init__(message)
        self.path = path


def default_ruleset():
    """No active presets: existing filters remain the default live policy."""
    return {"version": 1, "normalization": validate_options(), "include_legacy": True,
            "groups": [], "price": {"min": None, "max": None}, "sources": []}


def _object(value, allowed, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if set(value) - set(allowed):
        raise ValueError(f"Unknown field in {name}")


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must contain 1 to {maximum} characters")
    return value


def _term(term, normalized, normalization):
    _object(term, {"method", "value"}, "term")
    method = term.get("method", "contains")
    if not isinstance(method, str) or method not in {"contains", "exact", "regex"}:
        raise ValueError("Unknown term method")
    value = _text(term.get("value"), "term.value", 256 if method == "regex" else 1024)
    if method == "regex":
        for repetition in re.finditer(r"(?<!\\)\{(\d+)(?:,(\d*))?\}", value):
            if any(int(bound) > 10_000 for bound in repetition.groups() if bound):
                raise ValueError("Regular expression repetitions must not exceed 10000")
        try:
            re.compile(value)
            regex.compile(value, regex.VERSION0)
        except (re.error, regex.error, OverflowError):
            raise ValueError("Invalid regular expression") from None
    elif normalized:
        if not normalize_title(value, normalization):
            raise ValueError("Normalized term must not be empty")
    return {"method": method, "value": value}


def _group(group, path, identifiers, normalization):
    _object(group, {"id", "label", "policy", "match", "normalize", "terms"}, "group")
    identifier = _text(group.get("id"), "group.id", 64)
    if re.fullmatch(r"[A-Za-z0-9_-]+", identifier) is None or identifier in identifiers:
        raise ValueError("Group identifiers must be unique and contain letters, digits, underscores or hyphens")
    identifiers.add(identifier)
    label = _text(group.get("label", identifier), "group.label", 100)
    policy, combine = group.get("policy"), group.get("match", "any")
    if not isinstance(policy, str) or policy not in {"require", "exclude", "review"}:
        raise ValueError("Unknown group policy")
    if not isinstance(combine, str) or combine not in {"any", "all"}:
        raise ValueError("Group match must be any or all")
    normalized = _boolean(group.get("normalize", True), "group.normalize")
    terms = group.get("terms")
    if not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS_PER_GROUP:
        raise ValueError(f"Each group needs 1 to {MAX_TERMS_PER_GROUP} terms")
    canonical_terms = []
    for index, term in enumerate(terms):
        try:
            canonical_terms.append(_term(term, normalized, normalization))
        except ValueError as error:
            raise RulesetError(f"Term {index + 1}: {error}", f"{path}.terms.{index}") from None
    return {"id": identifier, "label": label, "policy": policy, "match": combine,
            "normalize": normalized, "terms": canonical_terms}


def validate_ruleset(data):
    """Validate every supplied field and return an independent canonical object.

    Errors are RulesetError (a ValueError) with the path of the field at fault.
    """
    result = default_ruleset()
    _object(data, result, "ruleset")
    version = data.get("version", 1)
    if type(version) is not int or version != 1:
        raise RulesetError("Unsupported ruleset version", "version")
    normalization = data.get("normalization", {})
    try:
        _object(normalization, result["normalization"], "normalization")
        result["normalization"] = validate_options(normalization)
    except ValueError as error:
        raise RulesetError(str(error), "normalization") from None
    try:
        result["include_legacy"] = _boolean(data.get("include_legacy", True), "include_legacy")
    except ValueError as error:
        raise RulesetError(str(error), "include_legacy") from None
    groups = data.get("groups", [])
    if not isinstance(groups, list) or len(groups) > MAX_GROUPS:
        raise RulesetError(f"groups must be a list with at most {MAX_GROUPS} groups", "groups")
    identifiers = set()
    for index, group in enumerate(groups):
        path = f"groups.{index}"
        try:
            result["groups"].append(_group(group, path, identifiers, result["normalization"]))
        except RulesetError as error:
            raise RulesetError(f"Group {index + 1}, {error}", error.path) from None
        except ValueError as error:
            raise RulesetError(f"Group {index + 1}: {error}", path) from None
    terms = [term for group in result["groups"] for term in group["terms"]]
    if len(terms) > MAX_TERMS or sum(term["method"] == "regex" for term in terms) > MAX_REGEX_TERMS:
        raise RulesetError(f"Rulesets allow at most {MAX_TERMS} terms and {MAX_REGEX_TERMS} regex terms", "groups")
    price = data.get("price", {})
    try:
        _object(price, {"min", "max"}, "price")
    except ValueError as error:
        raise RulesetError(str(error), "price") from None
    for bound in ("min", "max"):
        value = price.get(bound)
        if value is not None and (type(value) is not int or not 0 <= value <= 2 ** 63 - 1):
            raise RulesetError(f"price.{bound} must be a nonnegative integer or null", f"price.{bound}")
        result["price"][bound] = value
    minimum, maximum = result["price"]["min"], result["price"]["max"]
    if minimum is not None and maximum is not None and minimum > maximum:
        raise RulesetError("Minimum price must not exceed maximum price", "price")
    sources = data.get("sources", [])
    if not isinstance(sources, list) or len(sources) > len(SOURCES) or any(
            not isinstance(source, str) or source not in SOURCES for source in sources):
        raise RulesetError("sources must contain supported marketplace names", "sources")
    if len(sources) != len(set(sources)):
        raise RulesetError("sources must not contain duplicates", "sources")
    result["sources"] = sorted(sources)
    return result


@dataclass(frozen=True)
class Decision:
    verdict: str
    normalized_title: str
    reasons: list
    matched_groups: list
    legacy_matched_rules: list = field(default_factory=list)
    normalization_version: int = NORMALIZATION_VERSION

    @property
    def allowed(self):
        return self.verdict == "accepted"

    def payload(self):
        return {"verdict": self.verdict, "allowed": self.allowed,
                "normalized_title": self.normalized_title,
                "reasons": deepcopy(self.reasons), "matched_groups": list(self.matched_groups),
                "legacy_matched_rules": list(self.legacy_matched_rules),
                "normalization_version": self.normalization_version}


class _BudgetExceeded(Exception):
    pass


class CompiledRuleset:
    def __init__(self, ruleset, legacy_rules=()):
        self.ruleset = validate_ruleset(ruleset)
        self.groups = []
        for group in self.ruleset["groups"]:
            terms = []
            for term in group["terms"]:
                value = term["value"]
                if term["method"] == "regex":
                    # Rewriting regex source with casefold could change \D into \d.
                    # Preserve syntax; regex literals target normalized text.
                    flags = regex.VERSION0
                    if group["normalize"] and self.ruleset["normalization"]["casefold"]:
                        flags |= regex.IGNORECASE
                    value = regex.compile(value, flags)
                elif group["normalize"]:
                    value = normalize_title(value, self.ruleset["normalization"])
                terms.append((term["method"], value))
            self.groups.append((group, terms))
        try:
            legacy = list(islice(iter(legacy_rules), MAX_LEGACY_RULES + 1)) if self.ruleset["include_legacy"] else []
        except TypeError:
            raise ValueError("Legacy filters must be an iterable of FilterRule objects") from None
        if len(legacy) > MAX_LEGACY_RULES:
            raise ValueError(f"At most {MAX_LEGACY_RULES} legacy filters are supported")
        for rule in legacy:
            if not isinstance(rule, FilterRule):
                raise ValueError("Legacy filters must be FilterRule objects")
            if not isinstance(rule.method, str) or not isinstance(rule.policy, str):
                raise ValueError("Legacy filter method and policy must be text")
            _text(rule.value, "legacy filter value", 256 if rule.method == "regex" else 1024)
        self.legacy = FilterPolicy(legacy)
        self.legacy_patterns = [regex.compile(rule.value, regex.VERSION0) if rule.method == "regex" else None
                                for rule, _ in self.legacy.rules]
        self.has_regex = self.legacy.has_regex or any(method == "regex" for _, terms in self.groups for method, _ in terms)

    def evaluate(self, listing):
        if isinstance(listing, dict):
            title, source, price = listing.get("title"), listing.get("source"), listing.get("price")
        elif isinstance(listing, Listing):
            title, source, price = listing.title, listing.source, listing.price
        else:
            raise ValueError("Expected a Listing or saved listing object")
        reasons, matched_groups, legacy_matches = [], [], []
        blocked, uncertain = False, False

        def reason(code, message, group_id=None):
            values = {"code": code, "message": message}
            if group_id is not None:
                values["group_id"] = group_id
            reasons.append(values)

        if not isinstance(title, str):
            reason("missing_title", "The listing has no usable title.")
            return Decision("review", "", reasons, matched_groups)
        try:
            normalized = normalize_title(title, self.ruleset["normalization"])
        except ValueError:
            reason("title_limit", "The title exceeds the normalization limit.")
            return Decision("review", "", reasons, matched_groups)
        if not normalized.strip() or normalized.strip().casefold() == "unknown title":
            reason("missing_title", "The listing has no usable title.")
            return Decision("review", normalized, reasons, matched_groups)
        deadline = time.monotonic() + EVALUATION_BUDGET_SECONDS
        if self.ruleset["sources"]:
            if not isinstance(source, str) or not source:
                uncertain = True
                reason("missing_source", "The marketplace is unavailable.")
            elif source not in self.ruleset["sources"]:
                blocked = True
                reason("source_excluded", "The marketplace is outside the selected sources.")
        minimum, maximum = self.ruleset["price"]["min"], self.ruleset["price"]["max"]
        if minimum is not None or maximum is not None:
            if type(price) is not int or price < 0:
                uncertain = True
                reason("missing_price", "A valid price is required to apply the price limits.")
            elif minimum is not None and price < minimum:
                blocked = True
                reason("price_below_minimum", "The price is below the minimum.")
            elif maximum is not None and price > maximum:
                blocked = True
                reason("price_above_maximum", "The price is above the maximum.")
        for group, terms in self.groups:
            target = normalized if group["normalize"] else title
            matches, unknown = [], False
            for method, value in terms:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    unknown, uncertain = True, True
                    reason("evaluation_budget", "The total filter evaluation deadline was exceeded.", group["id"])
                    break
                try:
                    matched = (bool(value.search(target, timeout=min(FILTER_TIMEOUT_SECONDS, remaining))) if method == "regex"
                               else target == value if method == "exact" else value in target)
                    matches.append(matched)
                except TimeoutError:
                    unknown, uncertain = True, True
                    reason("filter_timeout", "A regular expression exceeded its evaluation deadline.", group["id"])
            matched = (any(matches) if group["match"] == "any" else len(matches) == len(terms) and all(matches))
            if matched:
                matched_groups.append(group["id"])
                if group["policy"] == "exclude":
                    blocked = True
                    reason("excluded_group_match", f'Excluded group "{group["label"]}" matched.', group["id"])
                elif group["policy"] == "review":
                    uncertain = True
                    reason("review_group_match", f'Group "{group["label"]}" needs review.', group["id"])
                else:
                    reason("required_group_match", f'Required group "{group["label"]}" matched.', group["id"])
            elif group["policy"] == "require" and not unknown:
                blocked = True
                reason("required_group_missing", f'Required group "{group["label"]}" did not match.', group["id"])
            if time.monotonic() >= deadline:
                if not any(value["code"] == "evaluation_budget" for value in reasons):
                    uncertain = True
                    reason("evaluation_budget", "The total filter evaluation deadline was exceeded.")
                break
        # Invoke the existing policy with its original raw-text matchers, wrapping
        # each matcher with this evaluation's local deadline. No shared mutable
        # deadline is retained on the compiled ruleset.
        bounded_legacy = FilterPolicy([])
        def bounded(matcher, pattern):
            def match(raw_title):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _BudgetExceeded()
                return bool(pattern.search(raw_title, timeout=min(FILTER_TIMEOUT_SECONDS, remaining))) if pattern else matcher(raw_title)
            return match
        bounded_legacy.rules = [(rule, bounded(matcher, pattern))
                                for (rule, matcher), pattern in zip(self.legacy.rules, self.legacy_patterns)]
        try:
            legacy_allowed, legacy_matches = bounded_legacy.evaluate(title)
            whitelists = [rule.id for rule, _ in self.legacy.rules if rule.policy == "whitelist"]
            for rule, _ in self.legacy.rules:
                if rule.id in legacy_matches:
                    code = "legacy_blacklist_match" if rule.policy == "blacklist" else "legacy_whitelist_match"
                    reason(code, f"Legacy {rule.policy} filter {rule.id} matched.")
            if not legacy_allowed:
                blocked = True
                if whitelists and not any(identifier in legacy_matches for identifier in whitelists):
                    reason("legacy_whitelist_missing", "No legacy whitelist filter matched the original title.")
        except FilterTimeout as error:
            uncertain = True
            reason("filter_timeout", f"Legacy filter {error.filter_id} exceeded its evaluation deadline.")
        except _BudgetExceeded:
            uncertain = True
            if not any(value["code"] == "evaluation_budget" for value in reasons):
                reason("evaluation_budget", "The total filter evaluation deadline was exceeded.")
        verdict = "filtered" if blocked else "review" if uncertain else "accepted"
        if verdict == "accepted" and not reasons:
            reason("accepted", "No active rule excluded this listing.")
        return Decision(verdict, normalized, reasons, matched_groups, legacy_matches)
