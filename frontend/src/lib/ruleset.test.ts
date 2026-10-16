import { describe, expect, it } from "vitest";

import type { Ruleset } from "../api/types";
import { describeRuleset } from "./describe";
import {
  cannotAddTerm, canonical, defaultRuleset, fieldLocation, groupsFromSearch, LIMITS, newGroup, parseRuleset, sameRuleset,
} from "./ruleset";

function ruleset(changes: Partial<Ruleset> = {}): Ruleset {
  return { ...defaultRuleset(), ...changes };
}

describe("canonical and sameRuleset", () => {
  it("ignores key order and source order", () => {
    const left = ruleset({ sources: ["surugaya", "mercari"], price: { max: 5000, min: 100 } });
    const right = ruleset({ sources: ["mercari", "surugaya"], price: { min: 100, max: 5000 } });
    expect(canonical(left).sources).toEqual(["mercari", "surugaya"]);
    expect(sameRuleset(left, right)).toBe(true);
  });

  it("sees a changed term", () => {
    const group = newGroup("require", "Poster", [{ method: "contains", value: "ポスター" }]);
    const changed = { ...group, terms: [{ method: "exact" as const, value: "ポスター" }] };
    expect(sameRuleset(ruleset({ groups: [group] }), ruleset({ groups: [changed] }))).toBe(false);
  });
});

describe("parseRuleset", () => {
  it("fills in defaults for missing fields", () => {
    const parsed = parseRuleset('{"groups": [{"terms": [{"value": "B1"}]}]}');
    expect(parsed.normalization).toEqual(defaultRuleset().normalization);
    expect(parsed.include_legacy).toBe(true);
    expect(parsed.price).toEqual({ min: null, max: null });
    expect(parsed.groups[0]).toMatchObject({ policy: "require", match: "any", normalize: true,
      terms: [{ method: "contains", value: "B1" }] });
    expect(parsed.groups[0]?.id).toMatch(/^require-[0-9a-f]{12}$/);
  });

  it("keeps the ids and labels it is given", () => {
    const parsed = parseRuleset('{"groups": [{"id": "accessories", "label": "Not frames", "policy": "exclude", "terms": []}]}');
    expect(parsed.groups[0]).toMatchObject({ id: "accessories", label: "Not frames", policy: "exclude" });
  });

  it.each([
    ["[]", "The JSON must be an object."],
    ['{"groups": {}}', "groups must be a list."],
    ['{"groups": [{"terms": [{"value": "x", "method": "glob"}]}]}', "Group 1, term 1 method must be one of: contains, exact, regex."],
    ['{"groups": [{"terms": []}, {"label": "no terms"}]}', "Group 2 needs a list of terms."],
    ['{"price": {"min": -1}}', "price.min must be a whole number of yen, or null."],
    ['{"sources": ["ebay"]}', "Each source must be one of: mercari, surugaya, yahooauction."],
    ['{"include_legacy": "yes"}', "include_legacy must be true or false."],
  ])("says what is wrong with %s", (text, message) => {
    expect(() => parseRuleset(text)).toThrow(message);
  });

  it("passes JSON syntax errors through", () => {
    expect(() => parseRuleset("{")).toThrow(SyntaxError);
  });
});

describe("cannotAddTerm", () => {
  const terms = (count: number, method: "contains" | "regex" = "contains") =>
    Array.from({ length: count }, (_, index) => ({ method, value: `term ${index}` }));

  it("allows a term below every limit", () => {
    const group = newGroup("require", "Words", terms(3));
    expect(cannotAddTerm(ruleset({ groups: [group] }), group, "contains")).toBeNull();
  });

  it("stops at the per-group limit, counting terms added from the same paste", () => {
    const group = newGroup("require", "Words", terms(LIMITS.termsPerGroup - 2));
    const rules = ruleset({ groups: [group] });
    expect(cannotAddTerm(rules, group, "contains", { terms: 1, regex: 0 })).toBeNull();
    expect(cannotAddTerm(rules, group, "contains", { terms: 2, regex: 0 })).toBe("A group holds at most 20 terms.");
  });

  it("stops at the total and the regex limits", () => {
    const full = Array.from({ length: 5 }, () => newGroup("require", "Words", terms(LIMITS.termsPerGroup)));
    const target = newGroup("exclude", "More");
    expect(cannotAddTerm(ruleset({ groups: [...full, target] }), target, "contains"))
      .toBe("Rules hold at most 100 terms in total.");
    const regex = newGroup("exclude", "Patterns", terms(LIMITS.regexTerms, "regex"));
    const other = newGroup("exclude", "Other");
    const rules = ruleset({ groups: [regex, other] });
    expect(cannotAddTerm(rules, other, "regex")).toBe("Rules hold at most 20 regex terms.");
    expect(cannotAddTerm(rules, other, "contains")).toBeNull();
  });
});

describe("fieldLocation", () => {
  it.each([
    ["groups.1.terms.2", { section: "groups", group: 1, term: 2 }],
    ["groups.0", { section: "groups", group: 0, term: undefined }],
    ["price.min", { section: "price" }],
    [undefined, {}],
  ])("reads %s", (field, location) => {
    expect(fieldLocation(field)).toEqual(location);
  });
});

describe("groupsFromSearch", () => {
  it("makes one must-match group per distinct word", () => {
    const groups = groupsFromSearch("beatmania  ポスター beatmania");
    expect(groups.map((group) => [group.label, group.policy, group.terms])).toEqual([
      ["beatmania", "require", [{ method: "contains", value: "beatmania" }]],
      ["ポスター", "require", [{ method: "contains", value: "ポスター" }]],
    ]);
  });
});

describe("describeRuleset", () => {
  it("names groups, marketplaces, price and the Discord filters", () => {
    const group = newGroup("require", "Words", [{ method: "contains", value: "B1" }, { method: "contains", value: "B2" }]);
    expect(describeRuleset(ruleset({ groups: [group], sources: ["mercari"], price: { min: 1000, max: null } })))
      .toBe("1 group with 2 terms; Mercari only; ￥1,000 or more; Discord filters on");
    expect(describeRuleset(ruleset({ include_legacy: false }))).toBe("No groups; Discord filters off");
  });
});
