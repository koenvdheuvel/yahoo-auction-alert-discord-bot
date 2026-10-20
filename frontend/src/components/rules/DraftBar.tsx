import CheckCircleOutlined from "@mui/icons-material/CheckCircleOutlined";
import CheckOutlined from "@mui/icons-material/CheckOutlined";
import ErrorOutlined from "@mui/icons-material/ErrorOutlined";
import ReplayOutlined from "@mui/icons-material/ReplayOutlined";
import UndoOutlined from "@mui/icons-material/UndoOutlined";
import WarningAmberOutlined from "@mui/icons-material/WarningAmberOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import type { AlertSummary } from "../../api/types";
import { visuallyHidden } from "../../lib/a11y";
import { formatRelative } from "../../lib/format";
import { useCompact, useKeyboardOpen, usePhone } from "../../lib/responsive";
import type { Draft } from "../../lib/useDraft";
import { MoreActions, type MoreAction } from "./MoreActions";

const NO_PERMISSION = "You need Manage Channels in this search's channel to publish";

interface Props {
  draft: Draft;
  /** Null for the scratch draft, which cannot be replayed or published. */
  alert: AlertSummary | null;
  /** The draft is being checked, or about to be. */
  checking: boolean;
  /** Why the check itself failed, or null. */
  checkFailed: string | null;
  /** Why the draft is invalid, or null. */
  invalid: string | null;
  /** When this exact draft was replayed, or null. */
  replayedAt: string | null;
  canPublish: boolean;
  /** Whether you may publish at all. */
  canChange: boolean;
  publishing: boolean;
  onPublish: () => void;
  onReplay: () => void;
}

type Tone = "warning" | "error" | "plain";

// The wide bar's caption keeps the colors it had. The narrow bar's single line reads like a title unless
// something is wrong.
const CAPTION_COLOR: Record<Tone, string> = { warning: "warning", error: "error", plain: "textSecondary" };
const LINE_COLOR: Record<Tone, string> = { warning: "warning.main", error: "error.main", plain: "text.primary" };

interface Status {
  icon: ReactNode;
  tone: Tone;
  /** The whole status, as the wide bar shows it and screen readers hear it. */
  text: string;
  /** One short line for narrow screens. */
  short: string;
}

function draftStatus({ draft, alert, checking, checkFailed, invalid, replayedAt }: Props): Status {
  if (draft.outdated) {
    const text = draft.published ? `Version ${draft.published.version} was published after you started this draft.`
      : "The rules changed after you started this draft.";
    return { icon: <WarningAmberOutlined color="warning" sx={{ fontSize: 15 }} />, tone: "warning", text, short: text };
  }
  if (checking) {
    return { icon: <CircularProgress size={12} aria-hidden="true" />, tone: "plain", text: "Checking the draft", short: "Checking the draft" };
  }
  if (checkFailed !== null) {
    const text = `The draft could not be checked: ${checkFailed}`;
    return { icon: null, tone: "error", text, short: text };
  }
  if (invalid !== null) return { icon: <ErrorOutlined color="error" sx={{ fontSize: 15 }} />, tone: "error", text: invalid, short: invalid };
  const icon = <CheckCircleOutlined color="success" sx={{ fontSize: 15 }} />;
  if (!draft.edited) {
    return { icon, tone: "plain", text: "Valid.",
      short: draft.published ? `Same as published version ${draft.published.version}` : "No rules published for this search" };
  }
  if (!alert) return { icon, tone: "plain", text: "Valid.", short: "Valid" };
  return replayedAt
    ? { icon, tone: "plain", text: `Valid. Replayed ${formatRelative(replayedAt)}.`, short: `Valid, replayed ${formatRelative(replayedAt)}` }
    : { icon, tone: "plain", text: "Valid. Not replayed yet.", short: "Valid, not replayed yet" };
}

/** The draft's state and its actions, kept at the bottom of the Rules tab. */
export function DraftBar(props: Props) {
  const { draft, alert, checkFailed, invalid, canPublish, canChange, publishing, onPublish, onReplay } = props;
  const compact = useCompact();
  const phone = usePhone();
  const keyboard = useKeyboardOpen();
  const status = draftStatus(props);
  const title = draft.edited
    ? draft.published ? `Unpublished changes to version ${draft.published.version}` : "Unpublished rules"
    : draft.published ? `Same as published version ${draft.published.version}` : "No rules published for this search";
  const publish = alert && (
    <Tooltip title={canChange ? "" : NO_PERMISSION}>
      <span>
        <Button variant="contained" onClick={onPublish} disabled={!canPublish || publishing || !canChange}>
          Publish
        </Button>
      </span>
    </Tooltip>
  );

  if (!compact) {
    return (
      <Box role="region" aria-label="Draft" sx={{ position: "sticky", bottom: 0, zIndex: 3, mx: -3, px: 3,
        py: 1.5, bgcolor: "background.paper", borderTop: 1, borderColor: "divider",
        display: "flex", flexWrap: "wrap", alignItems: "center", gap: 2 }}>
        <Box sx={{ flex: "1 1 280px", minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 650 }}>{title}</Typography>
          <Box aria-live="polite" sx={{ display: "flex", alignItems: "center", gap: 0.75, mt: 0.25, minHeight: 20 }}>
            {status.icon}
            <Typography variant="caption" color={CAPTION_COLOR[status.tone]}>{status.text}</Typography>
            {draft.outdated && (
              <>
                <Button size="small" color="inherit" onClick={draft.rebase} sx={{ py: 0 }}>Keep my draft</Button>
                <Button size="small" color="inherit" onClick={draft.discard} sx={{ py: 0 }}>Discard it</Button>
              </>
            )}
          </Box>
        </Box>
        <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
          {draft.edited && !draft.outdated && <Button color="inherit" onClick={draft.discard}>Discard changes</Button>}
          {alert && <Button variant="outlined" color="inherit" onClick={onReplay} disabled={Boolean(invalid)}>Replay draft</Button>}
          {publish}
        </Stack>
      </Box>
    );
  }

  // Narrow screens get one row: a short status, ⋮ for the other actions, and Publish where a thumb reaches it.
  // The bar steps aside while the on-screen keyboard is up, so it never covers the field being typed in. Phones
  // also hide it when there is nothing to do. Test a title is in the top bar and Replay in the bottom bar.
  const idle = !draft.edited && !draft.outdated && invalid === null && checkFailed === null;
  const hidden = keyboard || (phone && idle);
  const actions: MoreAction[] = [
    ...(draft.outdated ? [
      { label: "Keep my draft", icon: <CheckOutlined fontSize="small" />, onSelect: draft.rebase },
      { label: "Discard it", icon: <UndoOutlined fontSize="small" />, onSelect: draft.discard },
    ] : []),
    ...(alert ? [{ label: "Replay draft", icon: <ReplayOutlined fontSize="small" />, onSelect: onReplay, disabled: invalid !== null }] : []),
    ...(draft.edited && !draft.outdated ? [{ label: "Discard changes", icon: <UndoOutlined fontSize="small" />, onSelect: draft.discard }] : []),
  ];
  return (
    // While hidden, the region stays in the page out of sight, so screen readers still hear the status change.
    <Box role="region" aria-label="Draft" sx={hidden ? visuallyHidden : { position: "sticky", bottom: 0, zIndex: 3, mx: -2, px: 2, py: 1,
      bgcolor: "background.paper", borderTop: 1, borderColor: "divider" }}>
      <Box sx={visuallyHidden}>
        <Typography variant="body2">{title}</Typography>
        <Box aria-live="polite">{status.text}</Box>
      </Box>
      {/* The status column may shrink to nothing, so a long status is cut short instead of widening the page. */}
      <Box sx={{ display: hidden ? "none" : "grid", gridTemplateColumns: `minmax(0, 1fr)${actions.length ? " auto" : ""}${alert ? " auto" : ""}`,
        alignItems: "center", gap: 1 }}>
        {/* Screen readers get the whole status above. */}
        <Box aria-hidden="true" sx={{ minWidth: 0, display: "flex", alignItems: "center", gap: 0.75 }}>
          {status.icon}
          <Typography variant="body2" noWrap sx={{ fontWeight: 600, color: LINE_COLOR[status.tone] }}>
            {status.short}
          </Typography>
        </Box>
        {actions.length > 0 && (
          <MoreActions label="More draft actions" title={title} actions={actions} detail={
            <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>
              {status.text}{alert && !canChange ? ` ${NO_PERMISSION}.` : ""}
            </Typography>
          } />
        )}
        {publish}
      </Box>
    </Box>
  );
}
