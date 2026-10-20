import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import { lazy, Suspense, useMemo } from "react";
import type { ReactNode } from "react";

import { useGuildStatus } from "../../api/hooks";
import type { GuildStatus } from "../../api/types";
import { formatCount, formatRelative, plural } from "../../lib/format";
import { sharedSearchChannels } from "../../lib/graphs";
import type { StatusTab } from "../../lib/hooks";
import { useCompact } from "../../lib/responsive";
import { sourceName, STATUS_TABS } from "../../lib/vocabulary";
import { TOPBAR_HEIGHT } from "../../theme";
import { LoadError } from "../common/Feedback";
import { HelpTip } from "../common/HelpTip";
import { StatusSearches } from "../status/StatusSearches";

const GraphsSection = lazy(() => import("../status/GraphsSection").then((module) => ({ default: module.GraphsSection })));

const HELP = {
  bot: "Whether the bot is working. Ready means it is connected to Discord, its database answers, all of its background workers run, "
    + "and a check round finished recently enough (HEALTH_MAX_POLL_AGE). When it is not ready, searches may not be checked or posted until it recovers.",
  round: "When the bot last finished checking every search on every marketplace, including rounds where some checks failed. "
    + "The next round starts one check interval (CHECK_INTERVAL) after the previous one ended.",
  clean: "The last round in which every check worked. Below it, for each marketplace, the last round in which all of that marketplace's checks worked. "
    + "A time long ago means that marketplace keeps failing; the Searches table shows which searches and why.",
  waiting: "Posts and DMs for this server's searches that are queued but not yet accepted by Discord. They normally go out within seconds. "
    + "Failed ones gave up after several tries or a permanent error, such as a missing permission; the bot's operator can retry them.",
};

const fromSeconds = (value: number | null | undefined) => (value ? new Date(value * 1000).toISOString() : null);

function Card({ title, value, detail, tone, help }: { title: string; value: ReactNode; detail?: ReactNode; tone?: string; help?: string }) {
  // On phones the title and the value share a line, so the four cards take less of the screen.
  return (
    <Paper sx={{ p: { xs: 1.5, sm: 2 }, bgcolor: "background.paper", minWidth: 0, display: "grid", alignItems: "baseline",
      alignContent: "start", gridTemplateColumns: { xs: "minmax(0, 1fr) auto", sm: "minmax(0, 1fr)" }, columnGap: 2 }}>
      <Typography variant="overline" component="p" color="textSecondary">
        {title}
        {help && <HelpTip title={title} text={help} />}
      </Typography>
      <Typography variant="h2" component="p" sx={{ color: tone, mt: { xs: 0, sm: 0.5 } }}>{value}</Typography>
      {detail && <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5, gridColumn: "1 / -1" }}>{detail}</Typography>}
    </Paper>
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

interface Props {
  guildId: string;
  tab: StatusTab;
  onTab: (tab: StatusTab) => void;
  onOpenSearch: (alertId: string) => void;
  onOpenChannel: (channelId: string) => void;
}

/** The quick status overview stays separate from the on-demand Prometheus graphs. */
export function StatusView({ guildId, tab, onTab, onOpenSearch, onOpenChannel }: Props) {
  const compact = useCompact();
  const status = useGuildStatus(guildId);
  const channels = useMemo(() => sharedSearchChannels(status.data?.searches ?? []), [status.data]);
  return (
    <>
      {!compact && (
        <Box sx={{ px: 3, borderBottom: 1, borderColor: "divider", position: "sticky", top: TOPBAR_HEIGHT,
          bgcolor: "background.default", zIndex: 3 }}>
          <Tabs value={tab} onChange={(_, next: StatusTab) => onTab(next)} aria-label="Status sections">
            {(Object.keys(STATUS_TABS) as StatusTab[]).map((section) => (
              <Tab key={section} value={section} id={`status-tab-${section}`} aria-controls={`status-${section}-panel`}
                label={STATUS_TABS[section]} />
            ))}
          </Tabs>
        </Box>
      )}
      {/* Keep the overview's sort and page when visiting graphs, without keeping charts or their polling mounted. */}
      <Box id="status-overview-panel" role={compact ? "region" : "tabpanel"} hidden={tab !== "overview"}
        aria-label={compact ? STATUS_TABS.overview : undefined} aria-labelledby={compact ? undefined : "status-tab-overview"}
        sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
        {status.isPending ? <Skeleton variant="rounded" height={160} />
          : status.isError ? <LoadError error={status.error} what="The status" onRetry={() => void status.refetch()} />
            : <>
              <Bot status={status.data} />
              <StatusSearches searches={status.data.searches} onOpenSearch={onOpenSearch} onOpenChannel={onOpenChannel} />
            </>}
      </Box>
      <Box id="status-graphs-panel" role={compact ? "region" : "tabpanel"} hidden={tab !== "graphs"}
        aria-label={compact ? STATUS_TABS.graphs : undefined} aria-labelledby={compact ? undefined : "status-tab-graphs"}
        sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
        {tab === "graphs" && (
          <Suspense fallback={<Skeleton variant="rounded" height={260} />}>
            <GraphsSection guildId={guildId} channels={channels} onOpenSearch={onOpenSearch} />
          </Suspense>
        )}
      </Box>
    </>
  );
}
