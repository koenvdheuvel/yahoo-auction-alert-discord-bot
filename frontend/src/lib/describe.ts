import type { Ruleset } from "../api/types";
import { formatPrice, plural } from "./format";
import { totalTerms } from "./ruleset";
import { SOURCES } from "./vocabulary";

/** "3 groups with 12 terms; Mercari only; ¥1,000 or more; Discord filters on". */
export function describeRuleset(ruleset: Ruleset): string {
  const parts = [
    ruleset.groups.length ? `${plural(ruleset.groups.length, "group")} with ${plural(totalTerms(ruleset).terms, "term")}` : "No groups",
  ];
  if (ruleset.sources.length) parts.push(`${ruleset.sources.map((source) => SOURCES[source]).join(" and ")} only`);
  const { min, max } = ruleset.price;
  if (min !== null && max !== null) parts.push(`${formatPrice(min)} to ${formatPrice(max)}`);
  else if (min !== null) parts.push(`${formatPrice(min)} or more`);
  else if (max !== null) parts.push(`${formatPrice(max)} or less`);
  parts.push(ruleset.include_legacy ? "Discord filters on" : "Discord filters off");
  return parts.join("; ");
}
