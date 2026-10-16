import Alert from "@mui/material/Alert";

import { useCleanupStatus, useRemovalStatus } from "../../api/hooks";
import type { RemovalStatus } from "../../api/types";
import { formatCount, formatDateTime, plural } from "../../lib/format";

/** The latest post removal: progress while posts wait, then how it ended. */
export function RemovalRunNotice({ status, what = "Last post removal" }: { status: RemovalStatus | undefined; what?: string }) {
  const run = status?.run;
  if (!status || !run) return null;
  if (run.pending > 0) {
    return (
      <Alert severity="info" sx={{ mb: 2 }}>
        Removing Discord posts: {formatCount(run.removed)} of {formatCount(run.total)} done.
        {status.bot_running ? " New alert posts go first." : " The posts are removed when the bot runs next."}
      </Alert>
    );
  }
  const parts = [`${plural(run.removed, "post")} removed`];
  if (run.failed) parts.push(`${formatCount(run.failed)} could not be removed, see the bot logs`);
  if (run.cancelled) parts.push(`${formatCount(run.cancelled)} skipped because they were already gone or got 🔔 subscribers`);
  return (
    <Alert severity={run.failed ? "warning" : "success"} sx={{ mb: 2 }}>
      {what}, {formatDateTime(run.queued_at)}: {parts.join(", ")}.
    </Alert>
  );
}

/** The search's latest removal of posts its rules filter. */
export function RemovalProgress({ alertId }: { alertId: string }) {
  return <RemovalRunNotice status={useRemovalStatus(alertId).data} />;
}

/** The channel's latest cleanup. */
export function CleanupProgress({ channelId }: { channelId: string }) {
  return <RemovalRunNotice status={useCleanupStatus(channelId).data} what="Last cleanup" />;
}
