import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import { lazy, Suspense, useId, useMemo } from "react";
import type { ReactNode } from "react";

import { useGuildStatus } from "../../api/hooks";
import type { GuildStatus } from "../../api/types";
import { formatCount, formatRelative, plural } from "../../lib/format";
import { sharedSearchChannels } from "../../lib/graphs";
import type { SearchFilter, StatusTab } from "../../lib/hooks";
import { useCompact } from "../../lib/responsive";
import { hasCheckError } from "../../lib/searchInventory";
import { sourceName, STATUS_TABS } from "../../lib/vocabulary";
import { TOPBAR_HEIGHT } from "../../theme";
import { LoadError } from "../common/Feedback";
import { HelpTip } from "../common/HelpTip";
import { StatusProblems } from "../status/StatusProblems";

const GraphsSection = lazy(() => import("../status/GraphsSection").then((module) => ({ default: module.GraphsSection })));

const HELP = {
  bot: "Whether the bot is working. Ready means it is connected to Discord, its database answers, all of its background workers run, "
    + "and a check round finished recently enough (HEALTH_MAX_POLL_AGE). When it is not ready, searches may not be checked or posted until it recovers.",
  round: "When the bot last finished checking every search on every marketplace, including rounds where some checks failed. "
    + "The next round starts one check interval (CHECK_INTERVAL) after the previous one ended.",
  clean: "The last round in which every check worked. Below it, for each marketplace, the last round in which all of that marketplace's checks worked. "
    + "A time long ago means that marketplace keeps failing; the Searches page shows which searches and why.",
  queues: "Posts and DMs for this server's searches. Pending ones are queued but not yet accepted by Discord and normally go out within seconds. "
    + "Failed ones gave up after several tries or a permanent error, such as a missing permission; the bot's operator can retry them.",
};

const fromSeconds = (value: number | null | undefined) => (value ? new Date(value * 1000).toISOString() : null);

interface CardProps {
  title: string;
  value: string;
  detail?: ReactNode;
  tone?: string;
  help?: string;
  /** Opens the searches behind the number; the title's help control stays independent. */
  onOpen?: () => void;
}

const CARD_GRID = {
  display: "grid", alignItems: "baseline", alignContent: "start", width: "100%", textAlign: "left",
  gridTemplateColumns: { xs: "minmax(0, 1fr) auto", sm: "minmax(0, 1fr)" }, columnGap: 2,
} as const;

function Card({ title, value, detail, tone, help, onOpen }: CardProps) {
  // On phones the title and the value share a line, so the cards take less of the screen.
  const number = <Typography variant="h2" component="span" sx={{ display: "block", color: tone, mt: { xs: 0, sm: 0.5 } }}>{value}</Typography>;
  return (
    <Paper sx={{ ...CARD_GRID, bgcolor: "background.paper", minWidth: 0, p: { xs: 1.5, sm: 2 } }}>
      <Typography variant="overline" component="span" color="textSecondary" sx={{ display: "block" }}>
        {title}
        {help && <HelpTip title={title} text={help} />}
      </Typography>
      {onOpen ? (
        <ButtonBase onClick={onOpen} aria-label={`${title}: ${value}. Show them in Searches`}
          sx={{ justifyContent: "flex-start", borderRadius: 1, "&:hover": { bgcolor: "surface.hover" } }}>
          {number}
        </ButtonBase>
      ) : number}
      {detail && <Typography variant="body2" component="span" color="textSecondary" sx={{ display: "block", mt: 0.5, gridColumn: "1 / -1" }}>{detail}</Typography>}
    </Paper>
  );
}

function Section({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  const id = useId();
  return (
    <Box component="section" aria-labelledby={id} sx={{ mb: 3 }}>
      <Typography id={id} variant="h3" component="h2">{title}</Typography>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 1.5 }}>{note}</Typography>
      {children}
    </Box>
  );
}

const GRID = { display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", lg: "repeat(3, 1fr)" } } as const;

/** The bot's own health, which is the same whichever server is open. */
function BotHealth({ status }: { status: GuildStatus }) {
  const bot = status.bot;
  const note = "The bot is shared by every server on this dashboard, so this is the same for all of them.";
  if (!status.bot_running || !bot) {
    return (
      <Section title="Bot health" note={note}>
        <Alert severity="info">
          The bot does not run with this dashboard, so its health and the last checks are not known here. The counts below come from
          the database.
        </Alert>
      </Section>
    );
  }
  const lastPoll = fromSeconds(bot.last_poll_at);
  const lastSuccess = fromSeconds(bot.last_success_at);
  const next = bot.last_poll_at ? fromSeconds(bot.last_poll_at + status.interval_seconds) : null;
  return (
    <Section title="Bot health" note={note}>
      <Box sx={GRID}>
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
      </Box>
    </Section>
  );
}

/** This server's queues and failed checks. Each number with something behind it opens those searches. */
function ServerQueues({ status, onOpenSearches }: { status: GuildStatus; onOpenSearches: (filter: SearchFilter) => void }) {
  const { pending, failed } = status.totals;
  const waiting = status.searches.filter((search) => search.backlog.pending > 0).length;
  const failing = status.bot_running ? status.searches.filter(hasCheckError).length : null;
  return (
    <Section title="This server" note="Its own searches, from the database. The bot's posts and DMs for them are queued here until Discord accepts them.">
      <Box sx={GRID}>
        <Card title="Pending deliveries" help={HELP.queues} value={formatCount(pending)}
          detail={pending ? `Posts and DMs in ${plural(waiting, "search", "searches")}` : "Nothing waits to be sent"}
          onOpen={pending ? () => onOpenSearches("pending") : undefined} />
        <Card title="Failed deliveries" value={formatCount(failed)} tone={failed ? "error.main" : undefined}
          detail={failed ? "Posts and DMs that gave up" : "Nothing failed"}
          onOpen={failed ? () => onOpenSearches("failed") : undefined} />
        <Card title="Searches with check errors" value={failing === null ? "Unknown" : formatCount(failing)}
          tone={failing ? "error.main" : undefined}
          detail={failing === null ? "Needs the bot, which does not run with this dashboard"
            : failing ? `of ${plural(status.totals.searches, "search", "searches")} failed the last check` : "Every search passed its last check"}
          onOpen={failing ? () => onOpenSearches("errors") : undefined} />
      </Box>
    </Section>
  );
}

interface Props {
  guildId: string;
  tab: StatusTab;
  onTab: (tab: StatusTab) => void;
  onOpenSearch: (alertId: string) => void;
  /** Shows the server's Searches page with this quick filter. */
  onOpenSearches: (filter: SearchFilter) => void;
}

/** The quick status overview stays separate from the on-demand Prometheus graphs. */
export function StatusView({ guildId, tab, onTab, onOpenSearch, onOpenSearches }: Props) {
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
      <Box id="status-overview-panel" role={compact ? "region" : "tabpanel"} hidden={tab !== "overview"}
        aria-label={compact ? STATUS_TABS.overview : undefined} aria-labelledby={compact ? undefined : "status-tab-overview"}
        sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
        {tab === "overview" && (status.isPending ? <Skeleton variant="rounded" height={160} />
          : status.isError ? <LoadError error={status.error} what="The status" onRetry={() => void status.refetch()} />
            : <>
              <BotHealth status={status.data} />
              <ServerQueues status={status.data} onOpenSearches={onOpenSearches} />
              <StatusProblems searches={status.data.searches} botRunning={status.data.bot_running}
                onOpenSearch={onOpenSearch} onOpenSearches={onOpenSearches} />
            </>)}
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
