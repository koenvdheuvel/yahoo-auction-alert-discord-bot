import CollectionsOutlined from "@mui/icons-material/CollectionsOutlined";
import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import MonitorHeartOutlined from "@mui/icons-material/MonitorHeartOutlined";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import ScienceOutlined from "@mui/icons-material/ScienceOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Drawer from "@mui/material/Drawer";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import { useTheme } from "@mui/material/styles";
import Tooltip from "@mui/material/Tooltip";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useEffect, useState } from "react";

import { useAlerts, useChannels, useGuilds, useRules, useSession } from "../../api/hooks";
import type { AlertSummary, ArchiveTotals } from "../../api/types";
import { canChangeSearch, channelLabel, findChannel } from "../../lib/channels";
import { isTyping, usePlace } from "../../lib/hooks";
import { useDraft } from "../../lib/useDraft";
import { RAIL_WIDTH, SIDEBAR_WIDTH } from "../../theme";
import { ShortcutsDialog } from "../ShortcutsDialog";
import { LoadError } from "../common/Feedback";
import { TitleTestDialog, type TitleSeed, type TitleTest } from "../TitleTestDialog";
import { AddSearchDialog } from "../searches/AddSearchDialog";
import { UnregisterDialog } from "../searches/UnregisterDialog";
import { ChannelView } from "../views/ChannelView";
import { NotificationsView } from "../views/NotificationsView";
import { SearchView, ServerListingsView, type ListingFilters, type StoredReplay } from "../views/SearchView";
import { EverySearchView, SearchesView } from "../views/SearchesView";
import { StatusView } from "../views/StatusView";
import { ChannelIcon } from "./ChannelIcon";
import { ChannelSidebar } from "./ChannelSidebar";
import { ServerRail } from "./ServerRail";
import { TopBar } from "./TopBar";
import { UserPanel } from "./UserPanel";

const NO_TOTALS: ArchiveTotals = { archived_count: 0, unassigned_count: 0 };

/** The dashboard after sign-in: servers on the left, the picked server's channels, and the page. */
export function Shell() {
  const theme = useTheme();
  const wide = useMediaQuery(theme.breakpoints.up("md"));
  const [place, navigate] = usePlace();
  const session = useSession().data;
  const guilds = useGuilds();
  const alerts = useAlerts();
  const rules = useRules(place.alertId);
  const draft = useDraft(place.alertId, rules.data);
  const [navOpen, setNavOpen] = useState(false);
  const [titleTest, setTitleTest] = useState<TitleTest | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [adding, setAdding] = useState<{ channelId: string | null } | null>(null);
  const [unregistering, setUnregistering] = useState<AlertSummary | null>(null);
  const [replays, setReplays] = useState<Record<string, StoredReplay>>({});
  // "Replay draft" in the Rules tab opens Replay and starts it in one step.
  const [replayRequested, setReplayRequested] = useState(false);
  const [filters, setFilters] = useState<ListingFilters>({ search: "", source: "", verdict: "", feedback: "", latest: true });

  const notifications = session?.features?.notifications ?? false;
  const alert = alerts.data?.alerts.find((item) => item.id === place.alertId) ?? null;
  const missing = place.alertId !== null && alerts.isSuccess && alert === null;
  const known = guilds.data?.guilds ?? [];
  const managed = known.filter((item) => item.level === "manager");
  // A search's own server wins, then the server in the address, then the first one you manage.
  // Someone who manages none starts on their notifications.
  const guildId = alert?.guild_id
    ?? (known.some((guild) => guild.id === place.guildId) ? place.guildId : managed[0]?.id ?? null);
  const guild = known.find((item) => item.id === guildId) ?? null;
  // In a server where you are only a member, the only page is your notifications there.
  const memberHere = guild?.level === "member";
  const home = place.me || (guildId === null && notifications && guilds.isSuccess);
  const channels = useChannels(home || memberHere ? null : guildId);
  const guildName = guild?.name ?? channels.data?.guild.name ?? null;
  const serverSearches = (alerts.data?.alerts ?? []).filter((item) => item.guild_id === guildId);
  const channelSearches = place.channelId ? serverSearches.filter((item) => item.channel_id === place.channelId) : [];
  const channel = findChannel(channels.data, place.channelId);
  const view = home ? "me" : memberHere ? "member" : place.alertId ? "search" : place.channelId ? "channel" : place.view;

  const openTitleTest = (seed: TitleSeed = {}) =>
    setTitleTest((current) => ({ id: (current?.id ?? 0) + 1, seed, open: true }));
  const go = (next: Parameters<typeof navigate>[0]) => {
    navigate({ guildId, ...next });
    setNavOpen(false);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isTyping(event) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (document.querySelector(".MuiModal-root")) return;
      if (event.key === "?") {
        event.preventDefault();
        setHelpOpen(true);
      } else if (event.key === "t") {
        event.preventDefault();
        openTitleTest();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const heading = (() => {
    switch (view) {
      case "me":
        return { icon: notifications ? <NotificationsOutlined /> : <SearchOutlined />,
          title: notifications ? "Your notifications" : "Every server's searches", detail: null };
      case "member":
        return { icon: <NotificationsOutlined />, title: "Your notifications", detail: guildName };
      case "search":
        return { icon: <SearchOutlined />, title: alert?.search_query ?? "Search",
          detail: alert ? channelLabel(alert.channel_id, alert.channel_name) : null };
      case "channel":
        return { icon: <ChannelIcon kind={channel?.kind ?? "text"} />, title: channel?.name ?? `Channel ${place.channelId}`,
          detail: channel?.archived ? "Archived thread" : guildName };
      case "searches":
        return { icon: <SearchOutlined />, title: "Searches", detail: guildName };
      case "listings":
        return { icon: <CollectionsOutlined />, title: "All listings", detail: guildName };
      default:
        return { icon: <MonitorHeartOutlined />, title: "Status", detail: guildName };
    }
  })();

  useEffect(() => {
    document.title = `${heading.title} | ${session?.title ?? "Dashboard"}`;
  }, [heading.title, session?.title]);

  const page = (() => {
    const openChannel = (next: string, channelId: string) => go({ guildId: next, channelId, alertId: null, me: false });
    if (view === "member") {
      return <NotificationsView guildId={guildId} followHere={managed.length > 0} onOpenChannel={openChannel}
        canOpen={(id) => known.some((item) => item.id === id && item.level === "manager")} />;
    }
    if (view === "me") {
      return notifications
        ? <NotificationsView guildId={null} followHere={managed.length > 0} onOpenChannel={openChannel}
          canOpen={(id) => known.some((item) => item.id === id && item.level === "manager")} />
        : <EverySearchView searches={alerts.data?.alerts ?? []} onOpen={(item) => go({ guildId: item.guild_id, alertId: item.id, me: false })}
          guildName={(id) => (id ? known.find((item) => item.id === id)?.name ?? `Server ${id}` : "Searches without a known server")} />;
    }
    if (view === "search" && alert) {
      return <SearchView place={place} navigate={navigate} alert={alert} rules={rules} draft={draft} filters={filters}
        onFilters={setFilters} replays={replays} onReplay={(stored) => setReplays((current) => ({ ...current, [stored.alertId]: stored }))}
        replayRequested={replayRequested} setReplayRequested={setReplayRequested} onTestTitle={openTitleTest}
        canChange={canChangeSearch(channels.data, alert)}
        actions={
          <Tooltip title={canChangeSearch(channels.data, alert) ? "" : "You need Manage Channels in its channel"}>
            <span>
              <Button size="small" color="error" variant="outlined" startIcon={<DeleteOutlined />}
                disabled={!canChangeSearch(channels.data, alert)} onClick={() => setUnregistering(alert)}>Unregister</Button>
            </span>
          </Tooltip>
        } />;
    }
    if (view === "search") return null;
    if (guilds.isPending) return <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={120} /></Box>;
    if (guilds.isError) return <Box sx={{ p: 3 }}><LoadError error={guilds.error} what="The servers" onRetry={() => void guilds.refetch()} /></Box>;
    if (!guildId) {
      return <Box sx={{ p: 3 }}><Alert severity="info">There are no servers with searches yet. Run /register in a Discord channel.</Alert></Box>;
    }
    if (view === "channel") {
      return <ChannelView channelId={place.channelId!} guildId={guildId} channels={channels.data} searches={channelSearches}
        place={place} navigate={navigate} onAddSearch={() => setAdding({ channelId: place.channelId })}
        onUnregister={setUnregistering} />;
    }
    if (view === "searches") {
      return <SearchesView searches={serverSearches} channels={channels.data} onAdd={() => setAdding({ channelId: null })}
        onOpen={(item) => go({ alertId: item.id })} onOpenChannel={(channelId) => go({ channelId, alertId: null })}
        onUnregister={setUnregistering} />;
    }
    if (view === "listings") {
      const totals = alerts.data ? alerts.data.totals.guilds[guildId] ?? NO_TOTALS : undefined;
      return <ServerListingsView guildId={guildId} guildName={guildName} totals={totals} draft={draft} filters={filters}
        onFilters={setFilters} onTestTitle={openTitleTest} />;
    }
    return <StatusView guildId={guildId} onOpenSearch={(alertId) => go({ alertId })}
      onOpenChannel={(channelId) => go({ channelId, alertId: null })} />;
  })();

  const lists = (
    <Box sx={{ display: "flex", height: "100%", minHeight: 0 }}>
      <ServerRail guilds={guilds.data?.guilds} selectedId={guildId} home={home} bot={session?.bot ?? null}
        homeLabel={notifications ? "Your notifications" : "Every server's searches"}
        onHome={() => go({ me: true })} onSelect={(next) => go({ guildId: next, alertId: null, channelId: null, me: false, view: "status" })} />
      <ChannelSidebar guildName={guildName} channels={home || memberHere ? null : channels} alerts={alerts.data?.alerts}
        guildId={guildId} place={place} onNavigate={go} member={memberHere && !home}
        home={home ? { label: notifications ? "Home" : "Every server", notifications } : null}
        footer={<UserPanel onHelp={() => setHelpOpen(true)} />} />
    </Box>
  );

  return (
    <Box sx={{ display: "flex", height: "100dvh", overflow: "hidden", bgcolor: "background.default" }}>
      <Link href="#main" sx={{ position: "absolute", left: 8, top: -48, zIndex: 2000, bgcolor: "background.paper", p: 1,
        "&:focus": { top: 8 } }}>Skip to content</Link>
      {wide ? lists : (
        <Drawer open={navOpen} onClose={() => setNavOpen(false)}
          slotProps={{ paper: { sx: { width: RAIL_WIDTH + SIDEBAR_WIDTH, bgcolor: "surface.sidebar", backgroundImage: "none" } } }}>
          {lists}
        </Drawer>
      )}
      <Box component="main" id="main" tabIndex={-1} sx={{ flex: 1, minWidth: 0, overflowY: "auto", outline: "none" }}>
        <TopBar icon={heading.icon} title={heading.title} detail={heading.detail} showMenu={!wide} onMenu={() => setNavOpen(true)}
          onHelp={() => setHelpOpen(true)}
          actions={(view === "search" || view === "listings") && (
            <Button size="small" startIcon={<ScienceOutlined />} onClick={() => openTitleTest()} color="inherit" aria-keyshortcuts="t"
              sx={{ display: { xs: "none", sm: "inline-flex" } }}>
              Test a title
            </Button>
          )} />
        {missing && (
          <Alert severity="warning" sx={{ m: 3, mb: 0 }}
            action={<Link component="button" onClick={() => go({ alertId: null, view: "searches" })}>Show the searches</Link>}>
            This search is no longer registered, or it is in a server you no longer manage.
          </Alert>
        )}
        {page}
      </Box>
      <AddSearchDialog open={adding !== null} channels={channels.data} channelId={adding?.channelId ?? null}
        onClose={() => setAdding(null)} onCreated={(created) => { setAdding(null); go({ alertId: created.id }); }} />
      <UnregisterDialog alert={unregistering} onClose={() => setUnregistering(null)}
        onDone={() => {
          const gone = unregistering;
          setUnregistering(null);
          if (gone && place.alertId === gone.id) go({ alertId: null, channelId: gone.channel_id });
        }} />
      <TitleTestDialog test={titleTest} alert={alert} draft={draft} onClose={() => setTitleTest((current) => current && { ...current, open: false })} />
      <ShortcutsDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </Box>
  );
}
