import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import type { AlertSummary, AlertsResponse } from "../api/types";
import { formatCount, formatDateTime, formatRelative } from "../lib/format";
import type { Draft } from "../lib/useDraft";
import { channelName } from "../lib/vocabulary";
import { figures } from "../theme";

function Fact({ value, children, tone }: { value: ReactNode; children: ReactNode; tone?: string }) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "baseline", gap: 0.75 }}>
      <Box component="span" sx={{ fontWeight: 650, color: tone ?? "text.primary", ...figures, fontSize: "0.9375rem" }}>{value}</Box>
      <Box component="span" sx={{ color: "text.secondary", fontSize: "0.8125rem" }}>{children}</Box>
    </Box>
  );
}

interface Props {
  alert: AlertSummary | null;
  totals: AlertsResponse["totals"] | undefined;
  draft: Draft;
}

export function AlertHeader({ alert, totals, draft }: Props) {
  return (
    <Box component="header" sx={{ px: { xs: 2, md: 3 }, pt: 3, pb: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ justifyContent: "space-between", alignItems: { sm: "flex-start" } }}>
        <Typography variant="h1" sx={{ overflowWrap: "anywhere" }}>{alert ? alert.search_query : "All listings"}</Typography>
        {alert && draft.ready && (
          <Box sx={{ textAlign: { sm: "right" }, flex: "none" }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {draft.published ? `Published rules: version ${draft.published.version}` : "No published rules yet"}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {draft.edited ? "Your draft has unpublished changes" : draft.published
                ? `Since ${formatDateTime(draft.published.created_at)}` : "Only the Discord filters apply"}
            </Typography>
          </Box>
        )}
      </Stack>
      <Stack direction="row" sx={{ mt: 1.25, flexWrap: "wrap", columnGap: 3, rowGap: 0.5 }}>
        {alert ? (
          <>
            <Fact value={channelName(alert)}>channel</Fact>
            <Fact value={formatCount(alert.listing_count)}>{alert.listing_count === 1 ? "listing" : "listings"}</Fact>
            <Fact value={formatCount(alert.review_count)} tone={alert.review_count ? "warning.main" : undefined}>need review</Fact>
            {alert.last_seen_at && (
              <Tooltip title={formatDateTime(alert.last_seen_at)}>
                <span><Fact value={formatRelative(alert.last_seen_at)}>last checked</Fact></span>
              </Tooltip>
            )}
          </>
        ) : totals ? (
          <>
            <Fact value={formatCount(totals.archived_count)}>saved decisions across all searches</Fact>
            {totals.unassigned_count > 0 && <Fact value={formatCount(totals.unassigned_count)}>from removed searches</Fact>}
          </>
        ) : null}
      </Stack>
    </Box>
  );
}
