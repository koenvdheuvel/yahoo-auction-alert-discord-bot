import type { Policy, RuleGroup, Ruleset, Source, Term, TermMethod } from "../api/types";
import { SOURCES } from "./vocabulary";

// The same limits filtering.py enforces; the server stays the authority.
export const LIMITS = { groups: 20, termsPerGroup: 20, terms: 100, regexTerms: 20, label: 100 } as const;

export function termLimit(method: TermMethod): number {
  return method === "regex" ? 256 : 1024;
}

export function defaultRuleset(): Ruleset {
  return {
    version: 1,
    normalization: { nfkc: true, casefold: true, collapse_whitespace: true, kana_fold: false },
    include_legacy: true,
    groups: [],
    price: { min: null, max: null },
    sources: [],
  };
}

/** Field order and sorting as validate_ruleset returns them, so two equal rulesets compare equal. */
export function canonical(ruleset: Ruleset): Ruleset {
  return {
    version: 1,
    normalization: {
      nfkc: ruleset.normalization.nfkc,
      casefold: ruleset.normalization.casefold,
      collapse_whitespace: ruleset.normalization.collapse_whitespace,
      kana_fold: ruleset.normalization.kana_fold,
    },
    include_legacy: ruleset.include_legacy,
    groups: ruleset.groups.map((group) => ({
      id: group.id,
      label: group.label,
      policy: group.policy,
      match: group.match,
      normalize: group.normalize,
      terms: group.terms.map((term) => ({ method: term.method, value: term.value })),
    })),
    price: { min: ruleset.price.min, max: ruleset.price.max },
    sources: [...ruleset.sources].sort(),
  };
}

export function sameRuleset(left: Ruleset, right: Ruleset): boolean {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function randomId(): string {
  // crypto.randomUUID needs a secure context; getRandomValues works everywhere.
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

const NEW_GROUP: Record<Policy, string> = { require: "Must match", exclude: "Exclude", review: "Hold for review" };

export function newGroup(policy: Policy, label = NEW_GROUP[policy], terms: Term[] = []): RuleGroup {
  return { id: `${policy}-${randomId()}`, label, policy, match: "any", normalize: true, terms };
}

/** One must-match group per word of the alert's search, as a starting point. */
export function groupsFromSearch(search: string): RuleGroup[] {
  const words = [...new Set(search.split(/\s+/).filter(Boolean))].slice(0, LIMITS.groups);
  return words.map((word) => newGroup("require", word, [{ method: "contains", value: word }]));
}

export function totalTerms(ruleset: Ruleset): { terms: number; regex: number } {
  const terms = ruleset.groups.flatMap((group) => group.terms);
  return { terms: terms.length, regex: terms.filter((term) => term.method === "regex").length };
}

/** Why another term cannot be added to this group, or null when it can. `added` counts terms
 * already accepted from the same paste, with how many of them are regex. */
export function cannotAddTerm(ruleset: Ruleset, group: RuleGroup, method: TermMethod,
  added = { terms: 0, regex: 0 }): string | null {
  const totals = totalTerms(ruleset);
  if (group.terms.length + added.terms >= LIMITS.termsPerGroup) return `A group holds at most ${LIMITS.termsPerGroup} terms.`;
  if (totals.terms + added.terms >= LIMITS.terms) return `Rules hold at most ${LIMITS.terms} terms in total.`;
  if (method === "regex" && totals.regex + added.regex >= LIMITS.regexTerms) {
    return `Rules hold at most ${LIMITS.regexTerms} regex terms.`;
  }
  return null;
}

/** Where a server field path such as "groups.1.terms.0" points. */
export function fieldLocation(field: string | undefined): { group?: number; term?: number; section?: string } {
  if (!field) return {};
  const parts = field.split(".");
  if (parts[0] !== "groups") return { section: parts[0] };
  const group = parts[1] === undefined ? undefined : Number(parts[1]);
  const term = parts[2] === "terms" && parts[3] !== undefined ? Number(parts[3]) : undefined;
  return { section: "groups", group, term };
}

const SOURCE_NAMES = (Object.keys(SOURCES) as Source[]).sort();

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T, where: string): T {
  if (value === undefined) return fallback;
  if (typeof value === "string" && (allowed as readonly string[]).includes(value)) return value as T;
  throw new Error(`${where} must be one of: ${allowed.join(", ")}.`);
}

function flag(value: unknown, fallback: boolean, where: string): boolean {
  if (value === undefined) return fallback;
  if (typeof value === "boolean") return value;
  throw new Error(`${where} must be true or false.`);
}

function bound(value: unknown, where: string): number | null {
  if (value === undefined || value === null) return null;
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) return value;
  throw new Error(`${where} must be a whole number of yen, or null.`);
}

/**
 * Reads pasted JSON into the editor's shape. Values the editor cannot show are errors;
 * text rules (lengths, regex syntax, limits) are checked by the server's validation.
 */
export function parseRuleset(text: string): Ruleset {
  const data: unknown = JSON.parse(text);
  if (!isObject(data)) throw new Error("The JSON must be an object.");
  const base = defaultRuleset();
  const normalization = data.normalization === undefined ? {} : data.normalization;
  const price = data.price === undefined ? {} : data.price;
  const groups = data.groups === undefined ? [] : data.groups;
  const sources = data.sources === undefined ? [] : data.sources;
  if (!isObject(normalization)) throw new Error("normalization must be an object.");
  if (!isObject(price)) throw new Error("price must be an object.");
  if (!Array.isArray(groups)) throw new Error("groups must be a list.");
  if (!Array.isArray(sources)) throw new Error("sources must be a list.");
  return {
    version: 1,
    normalization: {
      nfkc: flag(normalization.nfkc, base.normalization.nfkc, "normalization.nfkc"),
      casefold: flag(normalization.casefold, base.normalization.casefold, "normalization.casefold"),
      collapse_whitespace: flag(normalization.collapse_whitespace, base.normalization.collapse_whitespace,
        "normalization.collapse_whitespace"),
      kana_fold: flag(normalization.kana_fold, base.normalization.kana_fold, "normalization.kana_fold"),
    },
    include_legacy: flag(data.include_legacy, true, "include_legacy"),
    groups: groups.map((group: unknown, index) => {
      const where = `Group ${index + 1}`;
      if (!isObject(group) || !Array.isArray(group.terms)) throw new Error(`${where} needs a list of terms.`);
      const policy = oneOf(group.policy, ["require", "exclude", "review"] as const, "require", `${where} policy`);
      const id = typeof group.id === "string" && group.id ? group.id : `${policy}-${randomId()}`;
      return {
        id,
        label: typeof group.label === "string" ? group.label : id,
        policy,
        match: oneOf(group.match, ["any", "all"] as const, "any", `${where} match`),
        normalize: flag(group.normalize, true, `${where} normalize`),
        terms: group.terms.map((term: unknown, termIndex) => {
          const termWhere = `${where}, term ${termIndex + 1}`;
          if (!isObject(term) || typeof term.value !== "string") throw new Error(`${termWhere} needs a text value.`);
          const method = oneOf(term.method, ["contains", "exact", "regex"] as const, "contains", `${termWhere} method`);
          return { method, value: term.value };
        }),
      };
    }),
    price: { min: bound(price.min, "price.min"), max: bound(price.max, "price.max") },
    sources: sources.map((source: unknown) => oneOf(source, SOURCE_NAMES, "mercari", "Each source")),
  };
}
