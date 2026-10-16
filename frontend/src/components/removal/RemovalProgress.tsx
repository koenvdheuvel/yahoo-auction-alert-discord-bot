import Alert from "@mui/material/Alert";

import { useRemovalStatus } from "../../api/hooks";
import { formatCount, formatDateTime, plural } from "../../lib/format";

/** The search's latest post removal: progress while posts wait, then how it ended. */
export function RemovalProgress({ alertId }: { alertId: string }) {
  const status = useRemovalStatus(alertId);
  const run = status.data?.run;
  if (!status.data || !run) return null;
  if (run.pending > 0) {
    return (
      <Alert severity="info" sx={{ mb: 2 }}>
        Removing Discord posts: {formatCount(run.removed)} of {formatCount(run.total)} done.
        {status.data.bot_running ? " New alert posts go first." : " The posts are removed when the bot runs next."}
      </Alert>
    );
  }
  const parts = [`${plural(run.removed, "post")} removed`];
  if (run.failed) parts.push(`${formatCount(run.failed)} could not be removed, see the bot logs`);
  if (run.cancelled) parts.push(`${formatCount(run.cancelled)} skipped because they were already gone or got 🔔 subscribers`);
  return (
    <Alert severity={run.failed ? "warning" : "success"} sx={{ mb: 2 }}>
      Last post removal, {formatDateTime(run.queued_at)}: {parts.join(", ")}.
    </Alert>
  );
}
