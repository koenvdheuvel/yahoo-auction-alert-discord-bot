"""Keep notification rules explicit while bounding user supplied regex work."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from domain import FilterPolicy, FilterRule, Listing, changes


ROOT = Path(__file__).resolve().parents[1]


class FilterPolicyTests(unittest.TestCase):
    def test_no_rules_admits_every_listing(self):
        self.assertEqual(FilterPolicy([]).evaluate("限定 vinyl"), (True, []))

    def test_whitelist_matches_are_or_combined(self):
        policy = FilterPolicy([
            FilterRule(1, "text", "whitelist", "vinyl"),
            FilterRule(2, "text", "whitelist", "限定"),
        ])
        self.assertEqual(policy.evaluate("限定 CD"), (True, [2]))
        self.assertEqual(policy.evaluate("vinyl record"), (True, [1]))
        self.assertEqual(policy.evaluate("vinyl 限定"), (True, [1, 2]))
        self.assertEqual(policy.evaluate("regular CD"), (False, []))

    def test_blacklist_vetoes_any_whitelist_match(self):
        policy = FilterPolicy([
            FilterRule(1, "text", "whitelist", "vinyl"),
            FilterRule(2, "text", "blacklist", "damaged"),
            FilterRule(3, "text", "blacklist", "replica"),
        ])
        self.assertEqual(policy.evaluate("damaged vinyl"), (False, [1, 2]))
        self.assertEqual(policy.evaluate("vinyl replica"), (False, [1, 3]))
        self.assertEqual(policy.evaluate("vinyl"), (True, [1]))

    def test_blacklist_only_policy_admits_nonmatching_titles(self):
        policy = FilterPolicy([FilterRule(1, "text", "blacklist", "damaged")])
        self.assertEqual(policy.evaluate("sealed vinyl"), (True, []))
        self.assertEqual(policy.evaluate("damaged vinyl"), (False, [1]))

    def test_text_matching_stays_case_sensitive(self):
        policy = FilterPolicy([FilterRule(1, "text", "whitelist", "VINYL")])
        self.assertEqual(policy.evaluate("vinyl"), (False, []))
        self.assertEqual(policy.evaluate("VINYL"), (True, [1]))

    def test_regex_matches_unicode_and_explicit_case_flags(self):
        policy = FilterPolicy([FilterRule(9, "regex", "whitelist", r"(?i)vinyl\s+限定\d+$")])
        self.assertEqual(policy.evaluate("Vinyl 限定12"), (True, [9]))
        self.assertEqual(policy.evaluate("Vinyl 限定12 replica"), (False, []))

    def test_regex_retains_stdlib_case_folding_behavior(self):
        # VERSION1 full case folding would expand ß to SS here.
        policy = FilterPolicy([FilterRule(9, "regex", "whitelist", "(?i)straße")])
        self.assertEqual(policy.evaluate("STRASSE"), (False, []))
        self.assertEqual(policy.evaluate("STRAẞE"), (True, [9]))

    def test_invalid_policy_method_and_stdlib_incompatible_regex_are_rejected(self):
        for rule in (FilterRule(1, "text", "unknown", "x"),
                     FilterRule(2, "unknown", "whitelist", "x")):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                FilterPolicy([rule])
        for pattern in ("[", "(?|a|b)"):
            with self.subTest(pattern=pattern), self.assertRaises(re.error):
                FilterPolicy([FilterRule(3, "regex", "whitelist", pattern)])

    def test_pathological_regex_times_out_with_the_responsible_filter_id(self):
        # A subprocess deadline also protects the suite against a future loss
        # of engine timeouts that would otherwise hang an in-process test.
        script = """
import json
import time
from domain import FilterPolicy, FilterRule, FilterTimeout
started = time.monotonic()
try:
    FilterPolicy([FilterRule(73, 'regex', 'whitelist', '(a|aa)+$')]).evaluate('a' * 500 + '!')
except FilterTimeout as error:
    print(json.dumps({'filter_id': error.filter_id, 'elapsed': time.monotonic() - started}))
else:
    raise SystemExit('Pathological regular expression was not timed out')
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["filter_id"], 73)
        self.assertLess(payload["elapsed"], 1)


class ListingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.before = Listing("item", "yahooauction", "vinyl", stock=1,
                              price=10_000, buyout_price=20_000)

    def test_stock_changes_only_notify_when_new_stock_exceeds_one(self):
        self.assertEqual(changes(self.before, replace(self.before, stock=0)), [])
        self.assertEqual(changes(self.before, replace(self.before, stock=1)), [])
        self.assertEqual(changes(self.before, replace(self.before, stock=2)),
                         ["Stock changed from 1 to 2"])
        self.assertEqual(changes(replace(self.before, stock=5), replace(self.before, stock=3)),
                         ["Stock changed from 5 to 3"])

    def test_price_drop_threshold_is_strict_and_increases_are_silent(self):
        self.assertEqual(changes(self.before, replace(self.before, price=9_500)), [])
        self.assertEqual(changes(self.before, replace(self.before, price=9_499)),
                         ["Price changed from ¥10000 to ¥9499"])
        self.assertEqual(changes(self.before, replace(self.before, price=10_501)), [])

    def test_buyout_changes_use_absolute_strict_threshold(self):
        self.assertEqual(changes(self.before, replace(self.before, buyout_price=20_500)), [])
        self.assertEqual(changes(self.before, replace(self.before, buyout_price=20_501)),
                         ["Buyout price changed from ¥20000 to ¥20501"])
        self.assertEqual(changes(self.before, replace(self.before, buyout_price=19_499)),
                         ["Buyout price changed from ¥20000 to ¥19499"])

    def test_payload_preserves_listing_values_and_serializes_end_time(self):
        ending = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        listing = replace(self.before, end_time=ending)
        payload = listing.payload()
        self.assertEqual(payload["end_time"], "2026-10-03T12:00:00+00:00")
        self.assertEqual(payload["id"], "item")
        self.assertIs(listing.end_time, ending)
        self.assertIsNone(self.before.payload()["end_time"])
