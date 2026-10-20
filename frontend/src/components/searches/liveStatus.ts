import { useMemo } from "react";

import { useGuildStatus } from "../../api/hooks";
import type { SearchStatus } from "../../api/types";
import { formatCount } from "../../lib/format";

/**
 * What the bot knows about a server's searches right now: their last checks and the posts and DMs that wait or
 * failed. It is not the same as nothing being wrong, so each state says what is missing.
 */
export type LiveStatus =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | {
    kind: "ready";
    /** False when the bot does not run with this dashboard: queues come from the database, checks are unknown. */
    botRunning: boolean;
    searches: ReadonlyMap<string, SearchStatus>;
  };

/** The server's live status, kept from the last answer while a refresh fails. */
export function useLiveStatus(guildId: string | null): LiveStatus {
  const { data, isError } = useGuildStatus(guildId);
  return useMemo((): LiveStatus => {
    if (data) return { kind: "ready", botRunning: data.bot_running, searches: new Map(data.searches.map((search) => [search.id, search])) };
    return { kind: isError ? "unavailable" : "loading" };
  }, [data, isError]);
}

/** How long the oldest waiting post has waited, when something waits. */
export function oldestText(status: SearchStatus): string | null {
  const oldest = status.backlog.oldest_pending_seconds;
  return status.backlog.pending && oldest ? `oldest ${Math.round(oldest / 60)} min` : null;
}

/** The search's posts and DMs that wait or failed, in words; null when none do. */
export function backlogText(status: SearchStatus): string | null {
  const { pending, failed } = status.backlog;
  if (!pending && !failed) return null;
  const oldest = oldestText(status);
  return [pending && `${formatCount(pending)} waiting`, failed && `${formatCount(failed)} failed`].filter(Boolean).join(", ")
    + (oldest ? `, ${oldest}` : "");
}
