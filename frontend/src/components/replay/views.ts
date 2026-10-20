import type { Change, ReplayItem } from "../../api/types";

/** Which replayed listings the list shows: one kind of change, every change, or everything checked. */
export type Show = "changes" | Change | "all";

/** The views, in the order of their buttons. */
export const SHOWS: Record<Show, string> = {
  changes: "Changed",
  newly_allowed: "Newly allowed",
  newly_blocked: "Newly filtered",
  changed: "Other changes",
  unchanged: "Unchanged",
  all: "Everything checked",
};

export function inView(item: ReplayItem, show: Show): boolean {
  if (show === "all") return true;
  if (show === "changes") return item.change !== "unchanged";
  return item.change === show;
}
