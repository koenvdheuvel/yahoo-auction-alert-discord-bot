import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { CheckResult } from "../../api/types";
import { formatDateTime, formatRelative, plural } from "../../lib/format";
import { latestCheck } from "../../lib/searchInventory";
import { sourceName } from "../../lib/vocabulary";


const OUTCOMES = { success: ["OK", "success"], error: ["Error", "error"], timeout: ["Timed out", "warning"] } as const;


/** Compact table summary; every marketplace's result, timing and error remains available on hover or keyboard focus. */
export function CheckSummary({ checks }: { checks: CheckResult[] | null }) {
  if (!checks?.length) return <NoChecks checks={checks} />;
  const failures = checks.filter((check) => check.outcome !== "success");
  const latest = latestCheck(checks);
  const label = failures.length === 1 ? `${sourceName(failures[0]!.source)} ${OUTCOMES[failures[0]!.outcome][0]}`
    : failures.length ? `${plural(failures.length, "check")} failed` : `${plural(checks.length, "check")} OK`;
  const color = failures.some((check) => check.outcome === "error") ? "error.main" : failures.length ? "warning.main" : "success.main";
  const details = checks.map((check) => {
    const finished = new Date(check.finished_at * 1000).toISOString();
    return `${sourceName(check.source)}: ${OUTCOMES[check.outcome][0]}. Finished ${formatDateTime(finished)}; took ${check.duration_seconds.toFixed(1)} s.`
      + (check.error ? ` ${check.error}` : "");
  }).join("\n");
  return (
    <Tooltip title={<Box sx={{ whiteSpace: "pre-line" }}>{details}</Box>} describeChild>
      <Box component="span" tabIndex={0} sx={{ display: "inline-flex", flexDirection: "column", cursor: "help" }}>
        <Typography variant="body2" component="span" sx={{ color }}>{label}</Typography>
        <Typography variant="caption" component="span" color="textSecondary">
          {formatRelative(latest === null ? null : new Date(latest * 1000).toISOString())}
        </Typography>
      </Box>
    </Tooltip>
  );
}

/** What a search's checks show where there are none to list. */
function NoChecks({ checks }: { checks: CheckResult[] | null }) {
  return (
    <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>
      {checks === null ? "Last checks are not known here" : "Not checked since the bot started"}
    </Typography>
  );
}

/** A card's last checks. What the desktop shows on hover is written out, since a finger cannot hover. */
export function CheckLines({ checks }: { checks: CheckResult[] | null }) {
  if (!checks?.length) return <NoChecks checks={checks} />;
  const latest = latestCheck(checks);
  return (
    <Box sx={{ mt: 1 }}>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
        {checks.map((check) => (
          <Chip key={check.source} variant="outlined" color={OUTCOMES[check.outcome][1]}
            label={`${sourceName(check.source)} ${check.outcome === "success" ? "✓" : OUTCOMES[check.outcome][0]}`} />
        ))}
      </Box>
      {checks.filter((check) => check.outcome !== "success").map((check) => (
        <Typography key={check.source} variant="body2" sx={{ mt: 0.5, color: `${OUTCOMES[check.outcome][1]}.main`, overflowWrap: "anywhere" }}>
          {sourceName(check.source)}: {check.outcome === "timeout"
            ? `timed out after ${check.duration_seconds.toFixed(1)} s`
            : check.error ?? "the check failed"}
        </Typography>
      ))}
      <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>
        Checked {formatRelative(latest === null ? null : new Date(latest * 1000).toISOString())}
      </Typography>
    </Box>
  );
}
