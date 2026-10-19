import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useMemo, type ReactNode } from "react";

import { useGuildStatus } from "../../api/hooks";
import type { CheckResult, GuildStatus, SearchStatus } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatCount, formatDateTime, formatRelative, plural } from "../../lib/format";
import { sharedSearchChannels } from "../../lib/graphs";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { LoadError } from "../common/Feedback";
import { HelpTip } from "../common/HelpTip";
import { GraphsSection } from "../status/GraphsSection";

const HELP = {
  bot: "Whether the bot is working. Ready means it is connected to Discord, its database answers, all of its background workers run, "
    + "and a check round finished recently enough (HEALTH_MAX_POLL_AGE). When it is not ready, searches may not be checked or posted until it recovers.",
  round: "When the bot last finished checking every search on every marketplace, including rounds where some checks failed. "
    + "The next round starts one check interval (CHECK_INTERVAL) after the previous one ended.",
  clean: "The last round in which every check worked. Below it, for each marketplace, the last round in which all of that marketplace's checks worked. "
    + "A time long ago means that marketplace keeps failing; the Searches table shows which searches and why.",
  waiting: "Posts and DMs for this server's searches that are queued but not yet accepted by Discord. They normally go out within seconds. "
    + "Failed ones gave up after several tries or a permanent error, such as a missing permission; the bot's operator can retry them.",
  searches: "Each search in this server: the result of its last check on each marketplace (hover a chip for when, how long and why), "
    + "how many listings it has found, and its posts and DMs that are waiting or failed. "
    + "Last checks are kept in memory, so they are empty for a while after the bot restarts.",
};

const fromSeconds = (value: number | null | undefined) => (value ? new Date(value * 1000).toISOString() : null);

function Card({ title, value, detail, tone, help }: { title: string; value: ReactNode; detail?: ReactNode; tone?: string; help?: string }) {
  return (
    <Paper sx={{ p: 2, bgcolor: "background.paper", minWidth: 0 }}>
      <Typography variant="overline" component="p" color="text.secondary">
        {title}
        {help && <HelpTip title={title} text={help} />}
      </Typography>
      <Typography variant="h2" component="p" sx={{ color: tone, mt: 0.5 }}>{value}</Typography>
      {detail && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{detail}</Typography>}
    </Paper>
  );
}

const OUTCOMES = { success: ["OK", "success"], error: ["Error", "error"], timeout: ["Timed out", "warning"] } as const;

function CheckChip({ check }: { check: CheckResult }) {
  const [label, color] = OUTCOMES[check.outcome];
  const finished = fromSeconds(check.finished_at);
  const detail = [`${sourceName(check.source)}: ${label.toLowerCase()} ${formatRelative(finished)}`,
    `took ${check.duration_seconds.toFixed(1)} s`, check.error && `(${check.error})`].filter(Boolean).join(", ");
  return (
    <Tooltip title={`${detail}. Finished ${formatDateTime(finished)}.`}>
      <Chip variant="outlined" color={color} label={`${sourceName(check.source)} ${check.outcome === "success" ? "✓" : label}`}
        sx={{ mr: 0.5, mb: 0.5 }} />
    </Tooltip>
  );
}

function Bot({ status }: { status: GuildStatus }) {
  const bot = status.bot;
  if (!status.bot_running || !bot) {
    return (
      <Alert severity="info" sx={{ mb: 2 }}>
        The bot does not run with this dashboard, so the last checks are not known here. The counts below come from
        the database.
      </Alert>
    );
  }
  const lastPoll = fromSeconds(bot.last_poll_at);
  const lastSuccess = fromSeconds(bot.last_success_at);
  const next = bot.last_poll_at ? fromSeconds(bot.last_poll_at + status.interval_seconds) : null;
  return (
    <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", lg: "repeat(4, 1fr)" }, mb: 3 }}>
      <Card title="Bot" help={HELP.bot} value={bot.ready ? "Ready" : bot.discord_connected ? "Not ready" : "Disconnected"}
        tone={bot.ready ? "success.main" : "error.main"}
        detail={bot.failed_worker ? `The ${bot.failed_worker} worker stopped.` : bot.database_available ? "Connected to Discord and the database." : "The database is not answering."} />
      <Card title="Last check round" help={HELP.round} value={lastPoll ? formatRelative(lastPoll) : "Not yet"}
        detail={next ? `Next one ${formatRelative(next)}` : `Every ${Math.round(status.interval_seconds / 60)} minutes`} />
      <Card title="Last round without errors" help={HELP.clean} value={lastSuccess ? formatRelative(lastSuccess) : "Not yet"}
        tone={!lastSuccess ? "warning.main" : undefined}
        detail={status.enabled_sources.map((source) => {
          const at = fromSeconds(bot.sources[source]);
          return `${sourceName(source)} ${at ? formatRelative(at) : "never"}`;
        }).join(", ")} />
      <Card title="Waiting to be sent" help={HELP.waiting} value={formatCount(status.totals.pending)}
        tone={status.totals.failed ? "error.main" : undefined}
        detail={status.totals.failed ? `${plural(status.totals.failed, "post or DM", "posts or DMs")} failed` : "Posts and DMs for this server"} />
    </Box>
  );
}

function Backlog({ search }: { search: SearchStatus }) {
  const { pending, failed, oldest_pending_seconds: oldest } = search.backlog;
  if (!pending && !failed) return <Typography variant="body2" color="text.secondary">Nothing waiting</Typography>;
  return (
    <Typography variant="body2" sx={{ color: failed ? "error.main" : undefined, ...figures }}>
      {[pending && `${formatCount(pending)} waiting`, failed && `${formatCount(failed)} failed`].filter(Boolean).join(", ")}
      {oldest ? `, oldest ${Math.round(oldest / 60)} min` : ""}
    </Typography>
  );
}

interface Props {
  guildId: string;
  onOpenSearch: (alertId: string) => void;
  onOpenChannel: (channelId: string) => void;
}

/** How the server's searches are doing: the bot, each search's last checks, and what waits to be posted. */
export function StatusView({ guildId, onOpenSearch, onOpenChannel }: Props) {
  const status = useGuildStatus(guildId);
  const channels = useMemo(() => sharedSearchChannels(status.data?.searches ?? []), [status.data]);
  if (status.isPending) return <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={160} /></Box>;
  if (status.isError) return <Box sx={{ p: 3 }}><LoadError error={status.error} what="The status" onRetry={() => void status.refetch()} /></Box>;
  const data = status.data;
  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
      <Bot status={data} />
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>
        Searches
        <HelpTip title="Searches" text={HELP.searches} />
      </Typography>
      {data.searches.length === 0 ? (
        <Typography variant="body2" color="text.secondary">No searches in this server yet.</Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small" aria-label="Search status">
            <TableHead>
              <TableRow>
                <TableCell>Search</TableCell>
                <TableCell>Channel</TableCell>
                <TableCell>Last checks</TableCell>
                <TableCell align="right">Listings</TableCell>
                <TableCell>Posts and DMs</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.searches.map((search) => (
                <TableRow key={search.id} hover>
                  <TableCell>
                    <Link component="button" onClick={() => onOpenSearch(search.id)} sx={{ fontWeight: 600, color: "text.primary" }}>
                      {search.search_query}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link component="button" color="inherit" onClick={() => onOpenChannel(search.channel_id)}>
                      {channelLabel(search.channel_id, search.channel_name)}
                    </Link>
                  </TableCell>
                  <TableCell>
                    {search.checks === null ? <Typography variant="body2" color="text.secondary">Unknown here</Typography>
                      : search.checks.length === 0 ? <Typography variant="body2" color="text.secondary">Not checked since the bot started</Typography>
                        : search.checks.map((check) => <CheckChip key={check.source} check={check} />)}
                  </TableCell>
                  <TableCell align="right" sx={figures}>{formatCount(search.listing_count)}</TableCell>
                  <TableCell><Backlog search={search} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
      <GraphsSection guildId={guildId} channels={channels} onOpenSearch={onOpenSearch} />
    </Box>
  );
}
