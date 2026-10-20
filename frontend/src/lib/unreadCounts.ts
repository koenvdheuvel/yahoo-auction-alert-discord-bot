import { createContext, useContext, useMemo } from "react";

import { useUnreadCounts } from "../api/hooks";
import type { UnreadAsk } from "../api/hooks";
import type { AlertSummary } from "../api/types";
import { SearchReadOwner, isIdentifier, useReadPositions } from "./searchReads";

/** What to show for one search. A search with nothing unread has no entry, and nothing is claimed while it is unknown. */
export type SearchUnreadState =
  | { kind: "count"; count: number }
  | { kind: "loading" }
  | { kind: "unavailable" };

export type SearchUnreadStates = ReadonlyMap<string, SearchUnreadState>;

const NONE: SearchUnreadStates = new Map();
export const SearchUnreadContext = createContext<SearchUnreadStates>(NONE);

/** The state of one search from the list the surrounding provider counts; null when there is nothing to show. */
export function useSearchUnread(alertId: string): SearchUnreadState | null {
  return useContext(SearchUnreadContext).get(alertId) ?? null;
}

/** Whether the search's newest listing lies after the cursor, which is when it has anything unread. */
function hasNewer(latest: string | null, readThrough: string | null): latest is string {
  return isIdentifier(latest) && (readThrough === null || BigInt(latest) > BigInt(readThrough));
}

/**
 * The one place that counts unread listings for a whole list of searches: one subscription to the read cursors and
 * one query, however many badges show it. Only searches whose newest listing is after their cursor are asked about;
 * for the others that listing is itself the proof of nothing unread. A count is only trusted for the cursor it was
 * asked about, so it can come back neither after the search was read nor for another person.
 */
export function useSearchUnreadStates(alerts: readonly AlertSummary[] | undefined): SearchUnreadStates {
  const owner = useContext(SearchReadOwner);
  const ids = useMemo(() => (alerts ?? []).map((alert) => alert.id), [alerts]);
  const positions = useReadPositions(ids);
  const asks = useMemo(() => {
    const unread: UnreadAsk[] = [];
    // Without a signed-in owner there is no read history to count against.
    if (owner === null) return unread;
    for (const alert of alerts ?? []) {
      const readThrough = positions.get(alert.id) ?? null;
      const latest = alert.latest_candidate_id;
      if (hasNewer(latest, readThrough)) unread.push([alert.id, readThrough, latest]);
    }
    return unread;
  }, [alerts, owner, positions]);
  const { data: answer, isError } = useUnreadCounts(owner, asks);

  return useMemo(() => {
    const states = new Map<string, SearchUnreadState>();
    for (const [alertId, readThrough] of asks) {
      if (answer?.owner === owner && Object.hasOwn(answer.asked, alertId) && answer.asked[alertId] === readThrough) {
        // A search the server left out is gone or no longer yours; it disappears from the list with the next refresh.
        const count = answer.counts[alertId];
        if (typeof count === "number" && count > 0) states.set(alertId, { kind: "count", count });
      } else {
        states.set(alertId, { kind: isError ? "unavailable" : "loading" });
      }
    }
    return states;
  }, [asks, answer, isError, owner]);
}
