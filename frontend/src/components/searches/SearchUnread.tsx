import Box from "@mui/material/Box";

import { formatCount, plural } from "../../lib/format";
import { useSearchUnread } from "../../lib/unreadCounts";
import { figures } from "../../theme";

const PILL = {
  display: "inline-grid", placeItems: "center", verticalAlign: "middle", flexShrink: 0, mx: 0.75, boxSizing: "border-box",
  minWidth: 16, height: 16, px: 0.5, borderRadius: 8, fontSize: "0.6875rem", fontWeight: 700, lineHeight: 1, ...figures,
} as const;

/** Separate from the review count: how many listings this person has not opened yet. Nothing shows when there are none. */
export function SearchUnread({ alertId }: { alertId: string }) {
  const state = useSearchUnread(alertId);
  if (state === null) return null;
  if (state.kind === "count") {
    const label = plural(state.count, "unread listing");
    return (
      <Box component="span" role="img" aria-label={label} title={label}
        sx={{ ...PILL, bgcolor: "surface.badge", color: "primary.contrastText" }}>
        {formatCount(state.count)}
      </Box>
    );
  }
  // Neither shows a number: the count is on its way, or could not be had.
  const label = state.kind === "loading" ? "Counting unread listings" : "Unread listings could not be counted";
  return (
    <Box component="span" role="img" aria-label={label} title={label}
      sx={{ ...PILL, border: 1, borderColor: "divider", color: "text.secondary" }}>
      {state.kind === "loading" ? "…" : "?"}
    </Box>
  );
}
