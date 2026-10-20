import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { useSession } from "../api/hooks";
import type { AlertSummary, ArchiveTotals } from "../api/types";
import { formatCount, formatDateTime, formatRelative } from "../lib/format";
import type { Draft } from "../lib/useDraft";
import { channelName, sourceName } from "../lib/vocabulary";
import { figures } from "../theme";
import { SheetDialog } from "./common/Sheet";

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
  totals: ArchiveTotals | undefined;
  /** The Discord server the totals cover, when the person picked one. */
  guildName: string | null;
  draft: Draft;
  /** Buttons for the search, such as Unregister. */
  actions?: ReactNode;
}

/** The published version, or what the draft changes about it. */
function RulesState({ draft }: { draft: Draft }) {
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {draft.published ? `Published rules: version ${draft.published.version}` : "No published rules yet"}
      </Typography>
      <Typography variant="caption" color="textSecondary">
        {draft.edited ? "Your draft has unpublished changes" : draft.published
          ? `Since ${formatDateTime(draft.published.created_at)}` : "Only the Discord filters apply"}
      </Typography>
    </Box>
  );
}

/** The counts for one search, or for all of them. `stacked` puts one per line, with full dates. */
function Facts({ alert, totals, guildName, stacked = false }: Omit<Props, "draft" | "actions"> & { stacked?: boolean }) {
  const lastSeen = alert?.last_seen_at;
  // The marketplaces the search checks, among those the bot searches at all.
  const enabled = useSession().data?.enabled_sources;
  const searched = alert ? alert.sources.filter((source) => !enabled || enabled.includes(source)).map(sourceName) : [];
  return (
    <Stack direction={stacked ? "column" : "row"} sx={{ flexWrap: "wrap", columnGap: 3, rowGap: stacked ? 1 : 0.5 }}>
      {alert ? (
        <>
          <Fact value={channelName(alert)}>channel</Fact>
          <Fact value={searched.length ? searched.join(", ") : "Nothing"} tone={searched.length ? undefined : "warning.main"}>searched</Fact>
          <Fact value={formatCount(alert.listing_count)}>{alert.listing_count === 1 ? "listing" : "listings"}</Fact>
          <Fact value={formatCount(alert.review_count)} tone={alert.review_count ? "warning.main" : undefined}>need review</Fact>
          {lastSeen && (stacked ? (
            <Fact value={formatRelative(lastSeen)}>last listing seen, {formatDateTime(lastSeen)}</Fact>
          ) : (
            <Tooltip title={formatDateTime(lastSeen)}>
              <span><Fact value={formatRelative(lastSeen)}>last listing seen</Fact></span>
            </Tooltip>
          ))}
        </>
      ) : totals ? (
        <>
          <Fact value={formatCount(totals.archived_count)}>
            {guildName ? `saved decisions across the searches in ${guildName}` : "saved decisions across all searches"}
          </Fact>
          {totals.unassigned_count > 0 && <Fact value={formatCount(totals.unassigned_count)}>from removed searches</Fact>}
        </>
      ) : null}
    </Stack>
  );
}

export function AlertHeader({ alert, totals, guildName, draft, actions }: Props) {
  return (
    <Box component="header" sx={{ px: { xs: 2, md: 3 }, pt: 3, pb: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ justifyContent: "space-between", alignItems: { sm: "flex-start" } }}>
        <Typography variant="h1" component="h2" sx={{ overflowWrap: "anywhere" }}>
          {alert ? alert.search_query : "All listings"}
        </Typography>
        {alert && draft.ready && (
          <Box sx={{ textAlign: { sm: "right" }, flex: "none", display: "flex", gap: 2, alignItems: "flex-start" }}>
            <RulesState draft={draft} />
            {actions}
          </Box>
        )}
      </Stack>
      <Box sx={{ mt: 1.25 }}><Facts alert={alert} totals={totals} guildName={guildName} /></Box>
    </Box>
  );
}

/** On phones the header is a sheet that opens from the title at the top, so the page starts near the top. */
export function AlertInfoSheet({ open, onClose, alert, totals, guildName, draft, actions }: Props & { open: boolean; onClose: () => void }) {
  return (
    <SheetDialog open={open} onClose={onClose} maxWidth="xs" aria-labelledby="alert-info-title">
      <DialogTitle id="alert-info-title" sx={{ overflowWrap: "anywhere" }}>{alert ? alert.search_query : "All listings"}</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2, justifyItems: "start" }}>
        {alert && draft.ready && <RulesState draft={draft} />}
        <Facts alert={alert} totals={totals} guildName={guildName} stacked />
        {actions}
      </DialogContent>
      <DialogActions><Button onClick={onClose} color="inherit">Close</Button></DialogActions>
    </SheetDialog>
  );
}
