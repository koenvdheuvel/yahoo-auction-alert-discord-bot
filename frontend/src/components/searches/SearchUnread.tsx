import Box from "@mui/material/Box";

import type { AlertSummary } from "../../api/types";
import { useSearchRead } from "../../lib/searchReads";

/** Separate from the review count: this person has not opened the latest listings yet. */
export function SearchUnread({ alert }: { alert: AlertSummary }) {
  const { unread } = useSearchRead(alert.id, alert.latest_candidate_id);
  return unread ? (
    <Box component="span" role="img" aria-label="Unread listings" title="Unread listings"
      sx={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", bgcolor: "primary.main", flexShrink: 0, mx: 0.75 }} />
  ) : null;
}
