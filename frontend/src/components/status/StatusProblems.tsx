import Box from "@mui/material/Box";
import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";

import type { SearchStatus } from "../../api/types";
import { formatCount, plural } from "../../lib/format";
import type { SearchFilter } from "../../lib/hooks";
import { hasCheckError, SEARCH_FILTER_NAMES } from "../../lib/searchInventory";
import { sourceName } from "../../lib/vocabulary";
import { backlogText } from "../searches/liveStatus";

/** How many searches a problem names; the rest are behind its link to Searches. */
const SAMPLE = 3;
/** Posts normally go out within seconds; one that has waited this long is a problem rather than a queue. */
const STUCK_SECONDS = 5 * 60;

interface Problem {
  filter: SearchFilter;
  summary: string;
  /** The worst searches first. */
  searches: { search: SearchStatus; detail: string }[];
  total: number;
}

function failedCheck(search: SearchStatus): string {
  const check = search.checks?.find((item) => item.outcome !== "success");
  if (!check) return "";
  return `${sourceName(check.source)}: ${check.outcome === "timeout" ? "timed out" : check.error ?? "the check failed"}`;
}

/** The server's problems, each as one line with the searches that are worst off, in the order to deal with them. */
function findProblems(searches: SearchStatus[], botRunning: boolean): Problem[] {
  const problems: Problem[] = [];
  const failed = searches.filter((search) => search.backlog.failed > 0).sort((a, b) => b.backlog.failed - a.backlog.failed);
  if (failed.length) {
    const posts = failed.reduce((sum, search) => sum + search.backlog.failed, 0);
    problems.push({ filter: "failed", total: failed.length,
      summary: `${plural(posts, "post or DM", "posts or DMs")} could not be sent, in ${plural(failed.length, "search", "searches")}`,
      searches: failed.map((search) => ({ search, detail: `${formatCount(search.backlog.failed)} failed` })) });
  }
  const failing = botRunning ? searches.filter(hasCheckError) : [];
  if (failing.length) {
    problems.push({ filter: "errors", total: failing.length,
      summary: `${plural(failing.length, "search", "searches")} failed the last check`,
      searches: failing.map((search) => ({ search, detail: failedCheck(search) })) });
  }
  const waiting = searches.filter((search) => search.backlog.pending > 0);
  const oldest = Math.max(0, ...waiting.map((search) => search.backlog.oldest_pending_seconds ?? 0));
  if (oldest >= STUCK_SECONDS) {
    const posts = waiting.reduce((sum, search) => sum + search.backlog.pending, 0);
    problems.push({ filter: "pending", total: waiting.length,
      summary: `${plural(posts, "post or DM", "posts or DMs")} waiting to be sent, the oldest for ${Math.round(oldest / 60)} min`,
      searches: [...waiting].sort((a, b) => (b.backlog.oldest_pending_seconds ?? 0) - (a.backlog.oldest_pending_seconds ?? 0))
        .map((search) => ({ search, detail: backlogText(search) ?? "" })) });
  }
  return problems;
}

interface Props {
  searches: SearchStatus[];
  botRunning: boolean;
  onOpenSearch: (alertId: string) => void;
  onOpenSearches: (filter: SearchFilter) => void;
}

/** What needs doing now, in a few lines. The full list of searches, with sorting and filters, is the Searches page. */
export function StatusProblems({ searches, botRunning, onOpenSearch, onOpenSearches }: Props) {
  const problems = findProblems(searches, botRunning);
  return (
    <Box component="section" aria-labelledby="status-problems" sx={{ mb: 3 }}>
      <Typography id="status-problems" variant="h3" component="h2" sx={{ mb: 1 }}>Needs attention</Typography>
      {problems.length === 0 ? (
        <Typography variant="body2" color="textSecondary">
          {botRunning
            ? "Every search passed its last check, and no post or DM has failed or waited long."
            : "No post or DM has failed or waited long. Check errors are not known without the bot."}
        </Typography>
      ) : (
        <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 1.5 }}>
          {problems.map((problem) => (
            <Box component="li" key={problem.filter}>
              <Typography variant="body1" component="p" sx={{ fontWeight: 600 }}>
                {problem.summary}.{" "}
                <Link component="button" sx={{ verticalAlign: "baseline" }} onClick={() => onOpenSearches(problem.filter)}
                  aria-label={`Show in Searches: ${SEARCH_FILTER_NAMES[problem.filter]}`}>
                  Show in Searches
                </Link>
              </Typography>
              <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
                {problem.searches.slice(0, SAMPLE).map(({ search, detail }) => (
                  <Typography key={search.id} component="li" variant="body2">
                    <Link component="button" onClick={() => onOpenSearch(search.id)} sx={{ color: "text.primary", textAlign: "left" }}>
                      {search.search_query}
                    </Link>
                    {detail && <Box component="span" sx={{ color: "text.secondary", overflowWrap: "anywhere" }}>: {detail}</Box>}
                  </Typography>
                ))}
                {problem.total > SAMPLE && (
                  <Typography component="li" variant="body2" color="textSecondary">and {formatCount(problem.total - SAMPLE)} more</Typography>
                )}
              </Box>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
