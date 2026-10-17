import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError, api } from "../../api/client";
import { useSession } from "../../api/hooks";
import type { AlertSummary, Ruleset, ReplayItem, ReplaySummary } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { formatCount, formatDateTime, formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import type { Draft } from "../../lib/useDraft";
import { CHANGES, VERDICTS, sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import type { StoredReplay } from "../views/SearchView";
import { DecisionButton } from "../common/Decision";
import { EmptyState } from "../common/Feedback";
import { ListingImage } from "../common/ListingImage";

type Show = "changes" | "newly_allowed" | "newly_blocked" | "all";

const SHOWS: Record<Show, { name: string; test: (item: ReplayItem) => boolean }> = {
  changes: { name: "Changed", test: (item) => item.change !== "unchanged" },
  newly_allowed: { name: "Newly allowed", test: (item) => item.change === "newly_allowed" },
  newly_blocked: { name: "Newly filtered", test: (item) => item.change === "newly_blocked" },
  all: { name: "Everything checked", test: () => true },
};

function Tally({ value, children, tone, onClick, active }: {
  value: number; children: ReactNode; tone?: string; onClick: () => void; active: boolean;
}) {
  return (
    <ButtonBase onClick={onClick} aria-pressed={active} sx={{ px: 1.5, py: 1, borderRadius: 1, border: 1,
      borderColor: active ? "text.primary" : "transparent", "&:hover": { bgcolor: "action.hover" } }}>
      <Box sx={{ textAlign: "left" }}>
        <Typography component="span" sx={{ display: "block", fontSize: "1.25rem", fontWeight: 680, color: value ? tone : "text.secondary",
          lineHeight: 1.2, ...figures }}>
          {formatCount(value)}
        </Typography>
        <Typography component="span" variant="body2" color="text.secondary">{children}</Typography>
      </Box>
    </ButtonBase>
  );
}

function Summary({ summary, show, onShow }: { summary: ReplaySummary; show: Show; onShow: (show: Show) => void }) {
  return (
    <Box>
      <Typography variant="subtitle2" component="h3" sx={{ mb: 0.5 }}>What the draft changes</Typography>
      <Stack direction="row" sx={{ flexWrap: "wrap", gap: 0.5 }}>
        <Tally value={summary.newly_allowed} tone="success.main" active={show === "newly_allowed"} onClick={() => onShow("newly_allowed")}>
          newly allowed
        </Tally>
        <Tally value={summary.newly_blocked} tone="text.primary" active={show === "newly_blocked"} onClick={() => onShow("newly_blocked")}>
          newly filtered
        </Tally>
        <Tally value={summary.changed} tone="warning.main" active={show === "changes"} onClick={() => onShow("changes")}>
          other changes, such as held for review
        </Tally>
        <Tally value={summary.unchanged} active={show === "all"} onClick={() => onShow("all")}>unchanged</Tally>
      </Stack>
    </Box>
  );
}

function Row({ item }: { item: ReplayItem }) {
  const candidate = item.candidate;
  const url = safeUrl(candidate.url);
  const title = candidate.title || "Untitled listing";
  return (
    <TableRow hover sx={{ "& td": { verticalAlign: "top" } }}>
      <TableCell sx={{ minWidth: 280 }}>
        <Stack direction="row" spacing={1.5}>
          <ListingImage src={candidate.image_url} size={56} />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" sx={{ fontWeight: 500, overflowWrap: "anywhere" }}>
              {url ? <Link href={url} target="_blank" rel="noopener noreferrer">{title}</Link> : title}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={figures}>
              {sourceName(candidate.source)} {formatPrice(candidate.price)}
            </Typography>
          </Box>
        </Stack>
      </TableCell>
      <TableCell><DecisionButton decision={item.original_decision} label={`Recorded ${formatDateTime(candidate.observed_at)}`} /></TableCell>
      <TableCell><DecisionButton decision={item.active_decision} label="Published rules" /></TableCell>
      <TableCell>
        <DecisionButton decision={item.draft_decision} label="Your draft" />
        {item.change !== "unchanged" && (
          <Typography variant="caption" color="text.secondary" component="p">
            {CHANGES[item.change]}, was {VERDICTS[item.active_decision.verdict].toLowerCase()}
          </Typography>
        )}
      </TableCell>
    </TableRow>
  );
}

interface Props {
  alert: AlertSummary | null;
  draft: Draft;
  stored: StoredReplay | null;
  onResult: (stored: StoredReplay) => void;
  /** Start a replay as soon as the panel opens, for "Replay draft" in the Rules tab. */
  autoRun: boolean;
  onAutoRun: () => void;
  onEditRules: () => void;
}

export function ReplayPanel({ alert, draft, stored, onResult, autoRun, onAutoRun, onEditRules }: Props) {
  const session = useSession();
  const [show, setShow] = useState<Show>("changes");
  const [page, setPage] = useState(0);
  const run = useMutation({
    mutationFn: (serialized: string) => api.replay(alert!.id, JSON.parse(serialized) as Ruleset),
    onSuccess: (result, serialized) => {
      onResult({ alertId: alert!.id, serialized, ranAt: new Date().toISOString(), result });
      setPage(0);
      setShow("changes");
    },
  });
  const items = useMemo(() => stored?.result.items.filter(SHOWS[show].test) ?? [], [stored, show]);
  const { mutate } = run;
  const autoStarted = useRef(false);

  useEffect(() => {
    if (!autoRun || autoStarted.current || !alert || !draft.ready) return;
    autoStarted.current = true;
    onAutoRun();
    mutate(draft.serialized);
  }, [autoRun, alert, draft.ready, draft.serialized, onAutoRun, mutate]);

  if (!alert) {
    return (
      <EmptyState title="Choose a search to replay">
        Replay checks your draft against listings a search found and compares it with the published rules.
      </EmptyState>
    );
  }

  const limit = session.data?.replay_limit ?? 500;
  const stale = stored !== null && stored.serialized !== draft.serialized;
  const summary = stored?.result.summary;
  const busy = run.error instanceof ApiError && run.error.code === "busy";
  const perPage = 50;

  return (
    <Box sx={{ display: "grid", gap: 2.5 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between", alignItems: { sm: "flex-start" } }}>
        <Box sx={{ maxWidth: 720 }}>
          <Typography variant="h2" component="h2">Compare the draft with the published rules</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Checks the latest decision of the {formatCount(limit)} most recently seen listings with both rule sets.
            Nothing is saved or posted.
          </Typography>
        </Box>
        <Button variant="contained" onClick={() => mutate(draft.serialized)} disabled={run.isPending || !draft.ready}
          sx={{ flex: "none" }}>
          {run.isPending ? "Replaying" : stored ? "Replay again" : "Replay draft"}
        </Button>
      </Stack>
      {run.isPending && <LinearProgress aria-label="Replaying" />}
      {run.isError && (
        <Alert severity={busy ? "warning" : "error"}>
          {busy ? "Another replay or title test is running. Try again in a moment." : `Replay failed: ${errorMessage(run.error)}`}
        </Alert>
      )}
      {!stored && !run.isPending && (
        <EmptyState title="Not replayed yet" action={draft.edited ? undefined : (
          <Button variant="outlined" color="inherit" onClick={onEditRules}>Edit the rules</Button>
        )}>
          {draft.edited
            ? "Replay the draft to see which listings it would allow or filter before you publish it."
            : "Your draft is the same as the published rules, so a replay shows no changes. Edit the rules first."}
        </EmptyState>
      )}
      {stored && summary && (
        <>
          {stale && (
            <Alert severity="info" action={<Button color="inherit" size="small" onClick={() => mutate(draft.serialized)}>Replay again</Button>}>
              The draft changed after this replay, so the results describe an earlier draft.
            </Alert>
          )}
          <Typography variant="caption" color="text.secondary" sx={figures}>
            Replayed {formatRelative(stored.ranAt)}: {plural(summary.total, "listing")} checked.
            {summary.truncated && !summary.budget_exceeded && summary.available > summary.recent
              ? ` This search has ${formatCount(summary.available)} listings; only the most recently seen were checked.` : ""}
          </Typography>
          {summary.budget_exceeded && (
            <Alert severity="warning">Replay stopped after 10 seconds, so not every listing was checked. The counts cover the checked ones.</Alert>
          )}
          <Summary summary={summary} show={show} onShow={(next) => { setShow(next); setPage(0); }} />
          <Box>
            <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1, mb: 1 }} role="group" aria-label="Show">
              {(Object.keys(SHOWS) as Show[]).map((key) => (
                <Button key={key} size="small" variant={show === key ? "contained" : "outlined"} color="inherit"
                  aria-pressed={show === key} onClick={() => { setShow(key); setPage(0); }}>
                  {SHOWS[key].name}
                </Button>
              ))}
            </Stack>
            {items.length === 0 ? (
              <EmptyState title="Nothing here">No checked listing falls in this group.</EmptyState>
            ) : (
              <TableContainer sx={{ border: 1, borderColor: "divider", borderRadius: 1, bgcolor: "background.paper" }}>
                <Table size="small" aria-label="Replay results">
                  <TableHead>
                    <TableRow>
                      <TableCell>Listing</TableCell>
                      <TableCell>Recorded then</TableCell>
                      <TableCell>Published rules</TableCell>
                      <TableCell>Your draft</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {items.slice(page * perPage, (page + 1) * perPage).map((item) => <Row key={item.candidate.id} item={item} />)}
                  </TableBody>
                </Table>
                <TablePagination component="div" count={items.length} page={page} rowsPerPage={perPage}
                  rowsPerPageOptions={[perPage]} onPageChange={(_, next) => setPage(next)}
                  labelDisplayedRows={({ from, to, count }) => `${formatCount(from)} to ${formatCount(to)} of ${formatCount(count)}`} />
              </TableContainer>
            )}
          </Box>
        </>
      )}
    </Box>
  );
}
