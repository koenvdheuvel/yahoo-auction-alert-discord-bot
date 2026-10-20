import type { AlertSummary, Change, Policy, Source, TermMethod, Verdict } from "../api/types";
import type { ChannelTab, Tab } from "./hooks";

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

/** A search's sections, in the order of its tabs. */
export const SEARCH_TABS: Record<Tab, string> = { listings: "Listings", rules: "Rules", replay: "Replay", versions: "Versions" };

/** A channel's sections, in the order of its tabs. */
export const CHANNEL_TABS: Record<ChannelTab, string> = { searches: "Searches", posts: "Posts", hidden: "Hidden", cleanup: "Cleanup" };
