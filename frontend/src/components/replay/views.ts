import type { Change, ReplayItem } from "../../api/types";

/** Which replayed listings the list shows: one kind of change, every change, or everything checked. */
export type Show = "changes" | Change | "all";

/** The views, in the order of their counters. Each counter shows how many listings its view holds. */
export const SHOWS: Record<Show, { label: string; tone?: string }> = {
  changes: { label: "changed" },
  newly_allowed: { label: "newly allowed", tone: "success.main" },
  newly_blocked: { label: "newly filtered", tone: "text.primary" },
  changed: { label: "other changes, such as held for review", tone: "warning.main" },
  unchanged: { label: "unchanged" },
  all: { label: "everything checked" },
};

export function inView(item: ReplayItem, show: Show): boolean {
  if (show === "all") return true;
  if (show === "changes") return item.change !== "unchanged";
  return item.change === show;
}
