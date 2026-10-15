from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import unittest

from domain import FilterRule, Listing
from filtering import CompiledRuleset, default_ruleset, validate_ruleset


ROOT = Path(__file__).resolve().parents[1]


def group(identifier, values, policy="require", combine="any", method="contains", normalize=True):
    return {"id": identifier, "label": identifier, "policy": policy, "match": combine,
            "normalize": normalize, "terms": [{"method": method, "value": value} for value in values]}


def rules(*groups, **overrides):
    values = default_ruleset()
    values["groups"] = list(groups)
    values.update(overrides)
    return values


def listing(title, **overrides):
    return replace(Listing("item", "yahooauction", title, 1, 5000), **overrides)


class FilteringTests(unittest.TestCase):
    def test_default_policy_has_no_presets_and_explains_accepted_listing(self):
        decision = CompiledRuleset(default_ruleset()).evaluate(listing("ガンダム ケースのみ"))
        self.assertEqual(decision.verdict, "accepted")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.payload()["normalized_title"], "ガンダム ケースのみ")
        self.assertEqual(decision.reasons[0]["code"], "accepted")
        self.assertEqual(decision.payload()["normalization_version"], 1)

    def test_subject_aliases_and_product_type_are_separate_required_groups(self):
        engine = CompiledRuleset(rules(group("subject", ["GUNDAM", "ガンダム"]),
                                       group("product", ["フィギュア", "figure"])))
        for title in ("ガンダム フィギュア", "ＧＵＮＤＡＭ ＦＩＧＵＲＥ"):
            decision = engine.evaluate(listing(title))
            self.assertEqual(decision.verdict, "accepted")
            self.assertEqual(decision.matched_groups, ["subject", "product"])
        for title in ("ガンダム クリアファイル", "別作品 フィギュア"):
            decision = engine.evaluate(listing(title))
            self.assertEqual(decision.verdict, "filtered")
            self.assertIn("required_group_missing", [reason["code"] for reason in decision.reasons])

    def test_all_terms_require_every_condition_within_one_group(self):
        engine = CompiledRuleset(rules(group("condition", ["未開封", "箱付き"], combine="all")))
        self.assertTrue(engine.evaluate(listing("ガンダム 未開封 箱付き")).allowed)
        self.assertEqual(engine.evaluate(listing("ガンダム 未開封")).verdict, "filtered")

    def test_phrase_specific_accessory_and_bundle_exclusions_veto_subject_match(self):
        engine = CompiledRuleset(rules(group("subject", ["ガンダム"]), group("product", ["フィギュア"]),
            group("accessory", ["台座のみ", "箱のみ", "専用ケース"], "exclude"),
            group("bundle", ["まとめ売り", "セット売り"], "exclude")))
        for title in ("ガンダム フィギュア 台座のみ", "ガンダム フィギュア まとめ売り"):
            decision = engine.evaluate(listing(title))
            self.assertEqual(decision.verdict, "filtered")
            self.assertIn("excluded_group_match", [reason["code"] for reason in decision.reasons])
        for title in ("ガンダム フィギュア 箱付き", "ガンダム フィギュア 本体のみ",
                      "ガンダム フィギュア スターターセット 1/8 B-01"):
            self.assertTrue(engine.evaluate(listing(title)).allowed, title)

    def test_review_terms_are_not_automatic_exclusions_and_block_live_delivery(self):
        engine = CompiledRuleset(rules(group("ambiguous", ["ジャンク", "おまけ"], "review")))
        decision = engine.evaluate(listing("ガンダム フィギュア おまけ付き"))
        self.assertEqual(decision.verdict, "review")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.matched_groups, ["ambiguous"])
        self.assertEqual(decision.reasons[0]["code"], "review_group_match")

    def test_known_exclusion_takes_precedence_over_review_tag(self):
        engine = CompiledRuleset(rules(group("accessory", ["箱のみ"], "exclude"), group("ambiguous", ["ジャンク"], "review")))
        decision = engine.evaluate(listing("ガンダム ジャンク 箱のみ"))
        self.assertEqual(decision.verdict, "filtered")
        self.assertEqual(decision.matched_groups, ["accessory", "ambiguous"])

    def test_raw_groups_preserve_case_and_width_while_normalized_terms_follow_options(self):
        normalized = CompiledRuleset(rules(group("subject", ["BABYMETAL"])))
        raw = CompiledRuleset(rules(group("subject", ["BABYMETAL"], normalize=False)))
        self.assertTrue(normalized.evaluate(listing("ＢＡＢＹＭＥＴＡＬ")).allowed)
        self.assertEqual(raw.evaluate(listing("ＢＡＢＹＭＥＴＡＬ")).verdict, "filtered")
        self.assertEqual(raw.evaluate(listing("babymetal")).verdict, "filtered")
        self.assertTrue(raw.evaluate(listing("BABYMETAL")).allowed)
        kana = CompiledRuleset(rules(group("subject", ["ガンダム"]), normalization={"kana_fold": True}))
        self.assertTrue(kana.evaluate(listing("がんだむ")).allowed)

    def test_exact_match_is_for_the_entire_selected_title(self):
        engine = CompiledRuleset(rules(group("exact", ["BABYMETAL"], method="exact")))
        self.assertTrue(engine.evaluate(listing("　ＢＡＢＹＭＥＴＡＬ　")).allowed)
        self.assertEqual(engine.evaluate(listing("BABYMETAL figure")).verdict, "filtered")

    def test_regex_syntax_and_case_sensitive_escape_are_not_casefolded(self):
        engine = CompiledRuleset(rules(group("letters", [r"^\D+$"], method="regex")))
        self.assertTrue(engine.evaluate(listing("ＦＩＧＵＲＥ")).allowed)
        self.assertEqual(engine.evaluate(listing("123")).verdict, "filtered")
        self.assertTrue(CompiledRuleset(rules(group("case", ["BABYMETAL"], method="regex"))).evaluate(listing("babymetal")).allowed)

    def test_price_limits_are_inclusive_and_missing_price_requires_review(self):
        engine = CompiledRuleset(rules(price={"min": 1000, "max": 5000}))
        for price in (1000, 5000):
            self.assertTrue(engine.evaluate(listing("figure", price=price)).allowed)
        for price in (999, 5001):
            self.assertEqual(engine.evaluate(listing("figure", price=price)).verdict, "filtered")
        for price in (None, "1000", True, -1):
            decision = engine.evaluate({"title": "figure", "price": price})
            self.assertEqual(decision.verdict, "review")
            self.assertEqual(decision.reasons[0]["code"], "missing_price")

    def test_source_selection_and_missing_source_are_explained(self):
        engine = CompiledRuleset(rules(sources=["mercari"]))
        self.assertTrue(engine.evaluate(listing("figure", source="mercari")).allowed)
        self.assertEqual(engine.evaluate(listing("figure")).verdict, "filtered")
        self.assertEqual(engine.evaluate({"title": "figure"}).verdict, "review")

    def test_missing_unknown_and_excessive_titles_require_review(self):
        engine = CompiledRuleset(default_ruleset())
        for title in (None, 123, "", "　", "Unknown Title", "ＵＮＫＮＯＷＮ　ＴＩＴＬＥ", "a" * 10001):
            with self.subTest(title=str(title)[:30]):
                self.assertEqual(engine.evaluate({"title": title}).verdict, "review")

    def test_legacy_policy_is_raw_case_sensitive_and_preserves_blacklist_veto(self):
        legacy = [FilterRule(1, "text", "whitelist", "VINYL"), FilterRule(2, "text", "blacklist", "damaged")]
        engine = CompiledRuleset(default_ruleset(), legacy)
        decision = engine.evaluate(listing("vinyl"))
        self.assertEqual(decision.verdict, "filtered")
        self.assertEqual(decision.reasons[0]["code"], "legacy_whitelist_missing")
        accepted = engine.evaluate(listing("VINYL"))
        self.assertTrue(accepted.allowed)
        self.assertEqual(accepted.legacy_matched_rules, [1])
        rejected = engine.evaluate(listing("damaged VINYL"))
        self.assertEqual(rejected.verdict, "filtered")
        self.assertEqual(rejected.legacy_matched_rules, [1, 2])
        self.assertIn("legacy_blacklist_match", [reason["code"] for reason in rejected.reasons])

    def test_legacy_whitelists_remain_or_combined_and_can_be_explicitly_disabled(self):
        legacy = [FilterRule(1, "text", "whitelist", "vinyl"), FilterRule(2, "text", "whitelist", "限定")]
        self.assertTrue(CompiledRuleset(default_ruleset(), legacy).evaluate(listing("限定 CD")).allowed)
        self.assertTrue(CompiledRuleset(rules(include_legacy=False), legacy).evaluate(listing("figure")).allowed)

    def test_compilation_and_decision_payload_do_not_mutate_inputs_or_future_results(self):
        data = rules(group("subject", ["figure"]))
        original = deepcopy(data)
        engine = CompiledRuleset(data)
        data["groups"][0]["terms"][0]["value"] = "accessory"
        self.assertTrue(engine.evaluate(listing("figure")).allowed)
        self.assertEqual(original["groups"][0]["terms"][0]["value"], "figure")
        decision = engine.evaluate(listing("figure"))
        payload = decision.payload()
        payload["reasons"][0]["message"] = "modified"
        payload["matched_groups"].clear()
        self.assertEqual(decision.matched_groups, ["subject"])
        self.assertNotEqual(decision.reasons[0]["message"], "modified")
        self.assertIsInstance(json.dumps(decision.payload(), ensure_ascii=False), str)

    def test_pathological_new_and_legacy_regex_produce_review_without_hanging(self):
        script = """
import json
import time
from domain import FilterRule
from filtering import CompiledRuleset, default_ruleset
started = time.monotonic()
rules = default_ruleset()
rules['groups'] = [{'id': 'subject', 'policy': 'require', 'terms': [{'method': 'regex', 'value': '(a|aa)+$'}]}]
new = CompiledRuleset(rules).evaluate({'title': 'a' * 500 + '!'})
legacy = CompiledRuleset(default_ruleset(), [FilterRule(7, 'regex', 'whitelist', '(a|aa)+$')]).evaluate({'title': 'a' * 500 + '!'})
print(json.dumps({'new': new.payload(), 'legacy': legacy.payload(), 'elapsed': time.monotonic() - started}))
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        for mode in ("new", "legacy"):
            self.assertEqual(payload[mode]["verdict"], "review")
            self.assertIn("filter_timeout", [reason["code"] for reason in payload[mode]["reasons"]])
        self.assertLess(payload["elapsed"], 1)

    def test_total_evaluation_work_has_a_deadline_across_many_regex_terms(self):
        script = """
import json
import time
from filtering import CompiledRuleset, default_ruleset
rules = default_ruleset()
rules['groups'] = [{'id': 'subject', 'policy': 'require', 'terms': [{'method': 'regex', 'value': '(a|aa)+$'}] * 20}]
started = time.monotonic()
decision = CompiledRuleset(rules).evaluate({'title': 'a' * 500 + '!'})
print(json.dumps({'result': decision.payload(), 'elapsed': time.monotonic() - started}))
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"]["verdict"], "review")
        self.assertIn("evaluation_budget", [reason["code"] for reason in payload["result"]["reasons"]])
        self.assertLess(payload["elapsed"], 1)


class RulesetValidationTests(unittest.TestCase):
    def test_defaults_and_canonical_source_order_are_independent(self):
        self.assertEqual(validate_ruleset({}), default_ruleset())
        data = {"sources": ["surugaya", "mercari"]}
        self.assertEqual(validate_ruleset(data)["sources"], ["mercari", "surugaya"])
        self.assertEqual(data["sources"], ["surugaya", "mercari"])
        default = default_ruleset()
        default["groups"].append(group("x", ["x"]))
        self.assertEqual(default_ruleset()["groups"], [])

    def test_unknown_fields_and_wrong_types_are_rejected_at_every_level(self):
        invalid = [None, [], {"unknown": True}, {"version": True}, {"version": 2},
            {"normalization": None}, {"normalization": {"unknown": True}},
            {"normalization": {"kana_fold": 1}}, {"include_legacy": "true"}, {"groups": {}},
            {"price": {"minimum": 1}}, {"price": {"min": True}}, {"price": {"max": -1}},
            {"price": {"min": 2, "max": 1}}, {"sources": ["unknown"]}, {"sources": [None]},
            {"sources": ["mercari", "mercari"]}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_ruleset(data)
        for field, value in (("policy", "unknown"), ("policy", []), ("match", "none"), ("match", {}),
                             ("normalize", 1), ("unknown", True), ("terms", []), ("id", "has space")):
            data = rules(group("subject", ["figure"]))
            data["groups"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_ruleset(data)
        for field, value in (("method", "unknown"), ("method", []), ("value", " "), ("value", None), ("unknown", True)):
            data = rules(group("subject", ["figure"]))
            data["groups"][0]["terms"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_ruleset(data)

    def test_oversized_work_and_duplicate_groups_are_rejected(self):
        invalid = [rules(*[group(str(index), ["x"]) for index in range(21)]),
                   rules(group("subject", ["x"] * 21)),
                   rules(*[group(str(index), ["x"] * 20) for index in range(6)]),
                   rules(group("a", ["x"] * 20, method="regex"), group("b", ["x"], method="regex")),
                   rules(group("same", ["a"]), group("same", ["b"])),
                   rules(group("long", ["x" * 1025])), rules(group("regex", ["x" * 257], method="regex"))]
        for data in invalid:
            with self.subTest(data=str(data)[:60]), self.assertRaises(ValueError):
                validate_ruleset(data)
        with self.assertRaises(ValueError):
            CompiledRuleset(default_ruleset(), [FilterRule(index, "text", "blacklist", "x") for index in range(51)])

    def test_invalid_or_unbounded_regex_source_is_rejected(self):
        for pattern in ("[", "(?|a|b)", "a{9999999999999999999999}"):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                validate_ruleset(rules(group("pattern", [pattern], method="regex")))


if __name__ == "__main__":
    unittest.main()
