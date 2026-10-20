import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Tag from "@mui/icons-material/Tag";
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
import { useState, type ReactNode } from "react";

import { useGuildStatus } from "../../api/hooks";
import type { CheckResult, GuildStatus, SearchStatus } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatCount, formatDateTime, formatRelative, plural } from "../../lib/format";
import { useCompact } from "../../lib/responsive";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { LoadError } from "../common/Feedback";
import { ActionSheet } from "../common/Sheet";
import { SearchCard, SearchCards } from "../searches/SearchCard";

const fromSeconds = (value: number | null | undefined) => (value ? new Date(value * 1000).toISOString() : null);

function Card({ title, value, detail, tone }: { title: string; value: ReactNode; detail?: ReactNode; tone?: string }) {
  // On phones the title and the value share a line, so the four cards take less of the screen.
  return (
    <Paper sx={{ p: { xs: 1.5, sm: 2 }, bgcolor: "background.paper", minWidth: 0, display: "grid", alignItems: "baseline",
      alignContent: "start", gridTemplateColumns: { xs: "minmax(0, 1fr) auto", sm: "minmax(0, 1fr)" }, columnGap: 2 }}>
      <Typography variant="overline" component="p" color="textSecondary">{title}</Typography>
      <Typography variant="h2" component="p" sx={{ color: tone, mt: { xs: 0, sm: 0.5 } }}>{value}</Typography>
      {detail && <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5, gridColumn: "1 / -1" }}>{detail}</Typography>}
    </Paper>
  );
}

const OUTCOMES = { success: ["OK", "success"], error: ["Error", "error"], timeout: ["Timed out", "warning"] } as const;

function chipLabel(check: CheckResult): string {
  return `${sourceName(check.source)} ${check.outcome === "success" ? "✓" : OUTCOMES[check.outcome][0]}`;
}

function CheckChip({ check }: { check: CheckResult }) {
  const [label, color] = OUTCOMES[check.outcome];
  const finished = fromSeconds(check.finished_at);
  const detail = [`${sourceName(check.source)}: ${label.toLowerCase()} ${formatRelative(finished)}`,
    `took ${check.duration_seconds.toFixed(1)} s`, check.error && `(${check.error})`].filter(Boolean).join(", ");
  return (
    <Tooltip title={`${detail}. Finished ${formatDateTime(finished)}.`}>
      <Chip variant="outlined" color={color} label={chipLabel(check)} sx={{ mr: 0.5, mb: 0.5 }} />
    </Tooltip>
  );
}

/** A card's last checks. What the desktop shows on hover is written out, since a finger cannot hover. */
function CheckLines({ checks }: { checks: CheckResult[] | null }) {
  if (checks === null) return null;
  if (checks.length === 0) {
    return <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>Not checked since the bot started</Typography>;
  }
  const latest = fromSeconds(Math.max(...checks.map((check) => check.finished_at)));
  return (
    <Box sx={{ mt: 1 }}>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
        {checks.map((check) => (
          <Chip key={check.source} variant="outlined" color={OUTCOMES[check.outcome][1]} label={chipLabel(check)} />
        ))}
      </Box>
      {checks.filter((check) => check.outcome !== "success").map((check) => (
        <Typography key={check.source} variant="body2" sx={{ mt: 0.5, color: `${OUTCOMES[check.outcome][1]}.main`, overflowWrap: "anywhere" }}>
          {sourceName(check.source)}: {check.outcome === "timeout"
            ? `timed out after ${check.duration_seconds.toFixed(1)} s`
            : check.error ?? "the check failed"}
        </Typography>
      ))}
      <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.5 }}>Checked {formatRelative(latest)}</Typography>
    </Box>
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
      <Card title="Bot" value={bot.ready ? "Ready" : bot.discord_connected ? "Not ready" : "Disconnected"}
        tone={bot.ready ? "success.main" : "error.main"}
        detail={bot.failed_worker ? `The ${bot.failed_worker} worker stopped.` : bot.database_available ? "Connected to Discord and the database." : "The database is not answering."} />
      <Card title="Last check round" value={lastPoll ? formatRelative(lastPoll) : "Not yet"}
        detail={next ? `Next one ${formatRelative(next)}` : `Every ${Math.round(status.interval_seconds / 60)} minutes`} />
      <Card title="Last round without errors" value={lastSuccess ? formatRelative(lastSuccess) : "Not yet"}
        tone={!lastSuccess ? "warning.main" : undefined}
        detail={status.enabled_sources.map((source) => {
          const at = fromSeconds(bot.sources[source]);
          return `${sourceName(source)} ${at ? formatRelative(at) : "never"}`;
        }).join(", ")} />
      <Card title="Waiting to be sent" value={formatCount(status.totals.pending)}
        tone={status.totals.failed ? "error.main" : undefined}
        detail={status.totals.failed ? `${plural(status.totals.failed, "post or DM", "posts or DMs")} failed` : "Posts and DMs for this server"} />
    </Box>
  );
}

function backlogText(search: SearchStatus): string | null {
  const { pending, failed, oldest_pending_seconds: oldest } = search.backlog;
  if (!pending && !failed) return null;
  return [pending && `${formatCount(pending)} waiting`, failed && `${formatCount(failed)} failed`].filter(Boolean).join(", ")
    + (oldest ? `, oldest ${Math.round(oldest / 60)} min` : "");
}

function Backlog({ search }: { search: SearchStatus }) {
  const text = backlogText(search);
  if (!text) return <Typography variant="body2" color="textSecondary">Nothing waiting</Typography>;
  return <Typography variant="body2" sx={{ color: search.backlog.failed ? "error.main" : undefined, ...figures }}>{text}</Typography>;
}

interface CardsProps {
  searches: SearchStatus[];
  onOpenSearch: (alertId: string) => void;
  onOpenChannel: (channelId: string) => void;
}

/** On phones and tablets each search is a card that opens it; a long press also offers its channel. */
function SearchStatusCards({ searches, onOpenSearch, onOpenChannel }: CardsProps) {
  // The search stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ search: SearchStatus; open: boolean } | null>(null);
  const picked = menu?.search;
  return (
    <>
      <SearchCards label="Search status">
        {searches.map((search) => {
          const backlog = backlogText(search);
          return (
            <SearchCard key={search.id} name={search.search_query} onOpen={() => onOpenSearch(search.id)}
              onMenu={() => setMenu({ search, open: true })}>
              <Typography variant="body2" color="textSecondary" sx={{ ...figures, mt: 0.25 }}>
                {channelLabel(search.channel_id, search.channel_name)} · {plural(search.listing_count, "listing")}
              </Typography>
              <CheckLines checks={search.checks} />
              {backlog && (
                <Typography variant="body2" sx={{ mt: 0.5, color: search.backlog.failed ? "error.main" : "text.primary", ...figures }}>
                  Posts and DMs: {backlog}
                </Typography>
              )}
            </SearchCard>
          );
        })}
      </SearchCards>
      <ActionSheet open={menu?.open ?? false} onClose={() => setMenu((current) => current && { ...current, open: false })}
        title={picked?.search_query ?? ""} actions={picked ? [
          { label: "Open the search", icon: <SearchOutlined />, onSelect: () => onOpenSearch(picked.id) },
          { label: `Open ${channelLabel(picked.channel_id, picked.channel_name)}`, icon: <Tag />,
            onSelect: () => onOpenChannel(picked.channel_id) },
        ] : []} />
    </>
  );
}

interface Props {
  guildId: string;
  onOpenSearch: (alertId: string) => void;
  onOpenChannel: (channelId: string) => void;
}

/** How the server's searches are doing: the bot, each search's last checks, and what waits to be posted. */
export function StatusView({ guildId, onOpenSearch, onOpenChannel }: Props) {
  const compact = useCompact();
  const status = useGuildStatus(guildId);
  if (status.isPending) return <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={160} /></Box>;
  if (status.isError) return <Box sx={{ p: 3 }}><LoadError error={status.error} what="The status" onRetry={() => void status.refetch()} /></Box>;
  const data = status.data;
  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
      <Bot status={data} />
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>Searches</Typography>
      {data.searches.length === 0 ? (
        <Typography variant="body2" color="textSecondary">No searches in this server yet.</Typography>
      ) : compact ? (
        <SearchStatusCards searches={data.searches} onOpenSearch={onOpenSearch} onOpenChannel={onOpenChannel} />
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
                    {search.checks === null ? <Typography variant="body2" color="textSecondary">Unknown here</Typography>
                      : search.checks.length === 0 ? <Typography variant="body2" color="textSecondary">Not checked since the bot started</Typography>
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
    </Box>
  );
}
