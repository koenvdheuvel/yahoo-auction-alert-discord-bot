import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError, api } from "../../api/client";
import { useSession } from "../../api/hooks";
import type { AlertSummary, Change, Ruleset } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { formatCount, formatRelative, plural } from "../../lib/format";
import type { Draft } from "../../lib/useDraft";
import { figures } from "../../theme";
import type { StoredReplay } from "../views/SearchView";
import { EmptyState } from "../common/Feedback";
import { ReplayResults } from "./ReplayResults";
import { SHOWS, inView, type Show } from "./views";

function Tally({ value, children, tone, onClick, active }: {
  value: number; children: ReactNode; tone?: string; onClick: () => void; active: boolean;
}) {
  return (
    <ButtonBase onClick={onClick} aria-pressed={active} sx={{ px: 1.5, py: 1, borderRadius: 1, border: 1,
      justifyContent: "flex-start", alignItems: "flex-start", bgcolor: { xs: "background.paper", sm: "transparent" },
      borderColor: active ? "text.primary" : "transparent",
      // A finger leaves hover behind after a tap, so only a mouse gets it.
      "@media (hover: hover)": { "&:hover": { bgcolor: "action.hover" } } }}>
      <Box sx={{ textAlign: "left" }}>
        <Typography component="span" sx={{ display: "block", fontSize: "1.25rem", fontWeight: 680, color: value ? tone : "text.secondary",
          lineHeight: 1.2, ...figures }}>
          {formatCount(value)}
        </Typography>
        <Typography component="span" variant="body2" color="textSecondary">{children}</Typography>
      </Box>
    </ButtonBase>
  );
}

// Each tally shows exactly its own group of listings, so the number always matches the list.
const TALLIES: { change: Change; label: string; tone?: string }[] = [
  { change: "newly_allowed", label: "newly allowed", tone: "success.main" },
  { change: "newly_blocked", label: "newly filtered", tone: "text.primary" },
  { change: "changed", label: "other changes, such as held for review", tone: "warning.main" },
  { change: "unchanged", label: "unchanged" },
];

function Summary({ counts, show, onShow }: { counts: Record<Change, number>; show: Show; onShow: (show: Show) => void }) {
  return (
    <Box>
      <Typography variant="subtitle2" component="h3" sx={{ mb: 0.5 }}>What the draft changes</Typography>
      {/* Two by two on phones, a row on larger screens. */}
      <Box sx={{ display: { xs: "grid", sm: "flex" }, gridTemplateColumns: "repeat(2, minmax(0, 1fr))", flexWrap: "wrap",
        gap: { xs: 1, sm: 0.5 } }}>
        {TALLIES.map((tally) => (
          <Tally key={tally.change} value={counts[tally.change]} tone={tally.tone} active={show === tally.change}
            onClick={() => onShow(tally.change)}>
            {tally.label}
          </Tally>
        ))}
      </Box>
    </Box>
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
  const views = useRef<HTMLDivElement>(null);
  const run = useMutation({
    mutationFn: (serialized: string) => api.replay(alert!.id, JSON.parse(serialized) as Ruleset),
    onSuccess: (result, serialized) => {
      onResult({ alertId: alert!.id, serialized, ranAt: new Date().toISOString(), result });
      setPage(0);
      setShow("changes");
    },
  });
  const items = useMemo(() => stored?.result.items.filter((item) => inView(item, show)) ?? [], [stored, show]);
  const counts = useMemo(() => {
    const result: Record<Change, number> = { newly_allowed: 0, newly_blocked: 0, changed: 0, unchanged: 0 };
    for (const item of stored?.result.items ?? []) result[item.change] += 1;
    return result;
  }, [stored]);
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
  const select = (next: Show) => {
    setShow(next);
    setPage(0);
    // On phones the views scroll sideways, so a tally can pick one that is out of sight.
    views.current?.querySelector(`[data-show="${next}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  return (
    // One column that never grows wider than the page, however wide the results are.
    <Box sx={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 2.5 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between", alignItems: { sm: "flex-start" } }}>
        <Box sx={{ maxWidth: 720 }}>
          <Typography variant="h2" component="h2">Compare the draft with the published rules</Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>
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
          <Typography variant="caption" color="textSecondary" sx={figures}>
            Replayed {formatRelative(stored.ranAt)}: {plural(summary.total, "listing")} checked.
            {summary.truncated && !summary.budget_exceeded && summary.available > summary.recent
              ? ` This search has ${formatCount(summary.available)} listings; only the most recently seen were checked.` : ""}
          </Typography>
          {summary.budget_exceeded && (
            <Alert severity="warning">Replay stopped after 10 seconds, so not every listing was checked. The counts cover the checked ones.</Alert>
          )}
          <Summary counts={counts} show={show} onShow={select} />
          <Box>
            {/* On phones the views are one row that scrolls sideways under the page's edges. */}
            <Stack ref={views} direction="row" role="group" aria-label="Show" sx={{ gap: 1, mb: 1,
              flexWrap: { xs: "nowrap", sm: "wrap" }, overflowX: { xs: "auto", sm: "visible" }, mx: { xs: -2, sm: 0 },
              px: { xs: 2, sm: 0 }, scrollPaddingInline: "16px", scrollbarWidth: "none", "&::-webkit-scrollbar": { display: "none" } }}>
              {(Object.keys(SHOWS) as Show[]).map((key) => (
                <Button key={key} data-show={key} size="small" variant={show === key ? "contained" : "outlined"} color="inherit"
                  aria-pressed={show === key} onClick={() => select(key)} sx={{ flex: "none" }}>
                  {SHOWS[key]}
                </Button>
              ))}
            </Stack>
            {items.length === 0 ? (
              <EmptyState title="Nothing here">No checked listing falls in this group.</EmptyState>
            ) : (
              <ReplayResults items={items} page={page} onPage={setPage} />
            )}
          </Box>
        </>
      )}
    </Box>
  );
}
