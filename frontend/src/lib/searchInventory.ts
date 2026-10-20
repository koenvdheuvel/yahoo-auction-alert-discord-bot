import type { AlertSummary, CheckResult, SearchStatus } from "../api/types";
import { channelLabel } from "./channels";
import type { SearchFilter } from "./hooks";
import type { SearchUnreadState } from "./unreadCounts";

/** What each quick filter is called, on its chip and wherever a page links to it. */
export const SEARCH_FILTER_NAMES: Record<SearchFilter, string> = {
  unread: "Unread",
  review: "Needs review",
  errors: "Check errors",
  pending: "Pending deliveries",
  failed: "Failed deliveries",
};

/** The filters that need what the bot knows right now rather than what the database holds. */
export const LIVE_FILTERS: readonly SearchFilter[] = ["errors", "pending", "failed"];

/** One search of the inventory with everything the table sorts and filters by. */
export interface InventoryRow {
  alert: AlertSummary;
  /** Live checks and queues; null when the status has nothing for this search, or none was loaded. */
  status: SearchStatus | null;
  /** The search's unread state; null when nothing is unread. */
  unread: SearchUnreadState | null;
}

/** Whether the last check of any marketplace failed or timed out; false when nothing is known. */
export const hasCheckError = (status: SearchStatus | null | undefined) =>
  status?.checks?.some((check) => check.outcome !== "success") ?? false;

/** When the newest check of any marketplace finished, in seconds; null when there is none or checks are unknown. */
export function latestCheck(checks: CheckResult[] | null | undefined): number | null {
  return checks?.length ? Math.max(...checks.map((check) => check.finished_at)) : null;
}

export function matchesFilter(row: InventoryRow, filter: SearchFilter): boolean {
  switch (filter) {
    case "unread": return row.unread?.kind === "count";
    case "review": return row.alert.review_count > 0;
    case "errors": return hasCheckError(row.status);
    case "pending": return (row.status?.backlog.pending ?? 0) > 0;
    case "failed": return (row.status?.backlog.failed ?? 0) > 0;
  }
}

export interface Criteria {
  text: string;
  /** Null for every channel. */
  channelId: string | null;
  quick: SearchFilter | null;
}

export function filterRows(rows: InventoryRow[], { text, channelId, quick }: Criteria): InventoryRow[] {
  const needle = text.trim().toLowerCase();
  return rows.filter((row) => {
    const { alert } = row;
    if (channelId !== null && alert.channel_id !== channelId) return false;
    if (quick !== null && !matchesFilter(row, quick)) return false;
    return !needle || alert.search_query.toLowerCase().includes(needle)
      || channelLabel(alert.channel_id, alert.channel_name).toLowerCase().includes(needle);
  });
}

export type SortKey = "search" | "channel" | "listings" | "unread" | "review" | "rules" | "seen" | "checked" | "waiting" | "failed";
export type Direction = "asc" | "desc";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** What a row is sorted by; null when it is unknown or has not happened, which sorts last in either direction. */
function sortValue({ alert, status, unread }: InventoryRow, key: SortKey): string | number | null {
  switch (key) {
    case "search": return alert.search_query;
    case "channel": return channelLabel(alert.channel_id, alert.channel_name);
    case "listings": return alert.listing_count;
    // Nothing unread has no entry; an unknown count must not pass as zero.
    case "unread": return unread === null ? 0 : unread.kind === "count" ? unread.count : null;
    case "review": return alert.review_count;
    case "rules": return alert.active_version_id ? 1 : 0;
    case "seen": {
      const at = alert.last_seen_at ? Date.parse(alert.last_seen_at) : NaN;
      return Number.isNaN(at) ? null : at;
    }
    case "checked": return latestCheck(status?.checks);
    case "waiting": return status ? status.backlog.pending : null;
    case "failed": return status ? status.backlog.failed : null;
  }
}

/** The order of searches that are equal in the chosen column, so the list never shuffles between refreshes. */
function tieOrder(a: AlertSummary, b: AlertSummary): number {
  return collator.compare(a.search_query, b.search_query)
    || collator.compare(channelLabel(a.channel_id, a.channel_name), channelLabel(b.channel_id, b.channel_name))
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

export function sortRows(rows: InventoryRow[], key: SortKey, direction: Direction): InventoryRow[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = sortValue(a, key);
    const y = sortValue(b, key);
    if (x === null || y === null) {
      if (x !== y) return x === null ? 1 : -1;
    } else {
      const order = typeof x === "string" ? collator.compare(x, y as string) : x - (y as number);
      if (order) return order * sign;
    }
    return tieOrder(a.alert, b.alert);
  });
}
