import type { ReactNode } from "react";

import type { AlertSummary } from "../../api/types";
import { SearchUnreadContext, useSearchUnreadStates } from "../../lib/unreadCounts";

/** Counts the unread listings of these searches once, for every badge below it. */
export function SearchUnreadProvider({ alerts, children }: { alerts: AlertSummary[] | undefined; children: ReactNode }) {
  const states = useSearchUnreadStates(alerts);
  return <SearchUnreadContext.Provider value={states}>{children}</SearchUnreadContext.Provider>;
}
