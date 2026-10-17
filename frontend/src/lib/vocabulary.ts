import type { AlertSummary, Change, Label, Policy, Source, TermMethod, Verdict } from "../api/types";

export const SOURCES: Record<Source, string> = {
  yahooauction: "Yahoo Auctions",
  mercari: "Mercari",
  surugaya: "Surugaya",
  rakuma: "Rakuma",
};

export function sourceName(source: string): string {
  return SOURCES[source as Source] ?? (source || "Unknown marketplace");
}

export const VERDICTS: Record<Verdict, string> = {
  accepted: "Allowed",
  filtered: "Filtered",
  review: "Needs review",
};

/** Theme colors for the bot's decisions: allowed green, review amber, filtered grey. */
export const VERDICT_COLOR: Record<Verdict, string> = {
  accepted: "success.main",
  review: "warning.main",
  filtered: "text.secondary",
};

/** Which mark the label draws on the listing photo. */
export type MarkShape = "circle" | "cross" | "question";

export interface LabelInfo {
  name: string;
  key: string;
  mark: MarkShape;
  hint: string;
}

/** In keyboard order: 1 to 5. */
export const LABELS: Record<Label, LabelInfo> = {
  relevant: { name: "Relevant", key: "1", mark: "circle", hint: "The listing this search is for" },
  wrong_product: { name: "Wrong product", key: "2", mark: "cross", hint: "Matches the words, but is another product" },
  accessory: { name: "Accessory", key: "3", mark: "cross", hint: "A part or extra, such as a frame or a case only" },
  bundle: { name: "Bundle", key: "4", mark: "cross", hint: "Sold together with other items" },
  unsure: { name: "Unsure", key: "5", mark: "question", hint: "Not sure yet; replay does not count it" },
};

export const LABEL_ORDER = Object.keys(LABELS) as Label[];

export const POLICIES: Record<Policy, { name: string; description: string }> = {
  require: { name: "Must match", description: "Listings that match no term in this group are filtered." },
  exclude: { name: "Exclude", description: "Listings that match this group are filtered, even when every must-match group matches." },
  review: { name: "Hold for review", description: "Listings that match this group are held as needs review instead of being sent." },
};

export const METHODS: Record<TermMethod, { name: string; description: string }> = {
  contains: { name: "Contains", description: "The title contains this text." },
  exact: { name: "Whole title", description: "The whole title is exactly this text." },
  regex: { name: "Regex", description: "A regular expression, matched against the title." },
};

export const CHANGES: Record<Change, string> = {
  newly_allowed: "Newly allowed",
  newly_blocked: "Newly filtered",
  changed: "Other change",
  unchanged: "No change",
};

/** "#posters" when the bot knows the channel's name, otherwise the end of its ID. */
export function channelName(alert: Pick<AlertSummary, "channel_id" | "channel_name">): string {
  return alert.channel_name ? `#${alert.channel_name}` : `Channel …${alert.channel_id.slice(-6)}`;
}
