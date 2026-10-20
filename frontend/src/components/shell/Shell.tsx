import CleaningServicesOutlined from "@mui/icons-material/CleaningServicesOutlined";
import CollectionsOutlined from "@mui/icons-material/CollectionsOutlined";
import DashboardOutlined from "@mui/icons-material/DashboardOutlined";
import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import ForumOutlined from "@mui/icons-material/ForumOutlined";
import GridViewOutlined from "@mui/icons-material/GridViewOutlined";
import HistoryOutlined from "@mui/icons-material/HistoryOutlined";
import MonitorHeartOutlined from "@mui/icons-material/MonitorHeartOutlined";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import ReplayOutlined from "@mui/icons-material/ReplayOutlined";
import ScienceOutlined from "@mui/icons-material/ScienceOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import ShowChartOutlined from "@mui/icons-material/ShowChartOutlined";
import StorefrontOutlined from "@mui/icons-material/StorefrontOutlined";
import TuneOutlined from "@mui/icons-material/TuneOutlined";
import VisibilityOffOutlined from "@mui/icons-material/VisibilityOffOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import { useTheme } from "@mui/material/styles";
import SwipeableDrawer from "@mui/material/SwipeableDrawer";
import Tooltip from "@mui/material/Tooltip";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useAlerts, useChannels, useGuilds, useRules, useSession } from "../../api/hooks";
import type { AlertSummary, ArchiveTotals } from "../../api/types";
import { canChangeSearch, channelLabel, channelTabs, findChannel } from "../../lib/channels";
import { ownsSidewaysTouch, useSwipe } from "../../lib/gestures";
import { isTyping, usePlace, type ChannelTab, type StatusTab, type Tab } from "../../lib/hooks";
import { useDraft } from "../../lib/useDraft";
import { CHANNEL_TABS, SEARCH_TABS, STATUS_TABS } from "../../lib/vocabulary";
import { RAIL_WIDTH, SIDEBAR_WIDTH } from "../../theme";
import { AlertInfoSheet } from "../AlertHeader";
import { ShortcutsDialog } from "../ShortcutsDialog";
import { LoadError } from "../common/Feedback";
import { TitleTestDialog, type TitleSeed, type TitleTest } from "../TitleTestDialog";
import { AddSearchDialog } from "../searches/AddSearchDialog";
import { MarketplacesDialog } from "../searches/MarketplacesDialog";
import { SearchUnreadProvider } from "../searches/SearchUnreadProvider";
import { UnregisterDialog } from "../searches/UnregisterDialog";
import { ChannelView } from "../views/ChannelView";
import { NotificationsView } from "../views/NotificationsView";
import { DEFAULT_LISTING_FILTERS, type ListingFilters } from "../../lib/listingFilters";
import { SearchView, ServerListingsView, type StoredReplay } from "../views/SearchView";
import { EverySearchView, SearchesView } from "../views/SearchesView";
import { StatusView } from "../views/StatusView";
import { ChannelIcon } from "./ChannelIcon";
import { ChannelSidebar } from "./ChannelSidebar";
import { SectionBar, type Section } from "./SectionBar";
import { ServerRail } from "./ServerRail";
import { TopBar } from "./TopBar";
import { UserPanel } from "./UserPanel";

const NO_TOTALS: ArchiveTotals = { archived_count: 0, unassigned_count: 0 };
// iOS goes back on a swipe from the left edge, so there the lists only open from a swipe further in.
const iOS = typeof navigator !== "undefined" && /iPad|iPhone|iPod/.test(navigator.userAgent);

const SEARCH_ICONS: Record<Tab, ReactNode> = {
  listings: <GridViewOutlined />, rules: <TuneOutlined />, replay: <ReplayOutlined />, versions: <HistoryOutlined />,
};
const CHANNEL_ICONS: Record<ChannelTab, ReactNode> = {
  searches: <SearchOutlined />, posts: <ForumOutlined />, hidden: <VisibilityOffOutlined />, cleanup: <CleaningServicesOutlined />,
};
const STATUS_ICONS: Record<StatusTab, ReactNode> = { overview: <DashboardOutlined />, graphs: <ShowChartOutlined /> };

/** The dashboard after sign-in: servers on the left, the picked server's channels, and the page. */
export function Shell() {
  const theme = useTheme();
  const wide = useMediaQuery(theme.breakpoints.up("md"));
  const [place, navigate] = usePlace();
  const session = useSession().data;
  const guilds = useGuilds();
  // Someone who is only a member everywhere manages no searches; the server refuses them those routes.
  const memberOnly = Boolean(session?.guilds?.length) && session!.guilds!.every((guild) => guild.level === "member");
  const alerts = useAlerts(!memberOnly);
  const rules = useRules(place.alertId);
  const draft = useDraft(place.alertId, rules.data);
  const [navOpen, setNavOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const main = useRef<HTMLElement>(null);
  const [titleTest, setTitleTest] = useState<TitleTest | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [adding, setAdding] = useState<{ channelId: string | null } | null>(null);
  const [marketplaces, setMarketplaces] = useState<AlertSummary | null>(null);
  const [unregistering, setUnregistering] = useState<AlertSummary | null>(null);
  const [replays, setReplays] = useState<Record<string, StoredReplay>>({});
  // "Replay draft" in the Rules tab opens Replay and starts it in one step.
  const [replayRequested, setReplayRequested] = useState(false);
  const [filters, setFilters] = useState<ListingFilters>(DEFAULT_LISTING_FILTERS);

  const notifications = session?.features?.notifications ?? false;
  // The access key opens everything; the server checks channels only for Discord users.
  const accessKey = session?.method === "access_key";
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
  // On a phone each page opens at its top, as it does in an app.
  const toTop = () => {
    if (!wide) main.current?.scrollTo({ top: 0 });
  };
  const go = (next: Parameters<typeof navigate>[0]) => {
    navigate({ guildId, ...next });
    setNavOpen(false);
    toTop();
  };
  // Like Discord's app: a swipe to the right anywhere on the page opens the server and channel lists.
  const swipe = useSwipe({ directions: ["right"], ignore: ownsSidewaysTouch, onSwipe: () => setNavOpen(true) });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isTyping(event) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (document.querySelector(".MuiModal-root:not(.MuiModal-hidden)")) return;
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
          detail: alert ? [guildName, channelLabel(alert.channel_id, alert.channel_name)].filter(Boolean).join(" · ") : guildName };
      case "channel":
        return { icon: <ChannelIcon kind={channel?.kind ?? "text"} />, title: channel?.name ?? `Channel ${place.channelId}`,
          detail: [guildName, channel?.archived ? "Archived thread" : null].filter(Boolean).join(" · ") || null };
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

  const changeable = alert !== null && (accessKey || canChangeSearch(channels.data, alert));
  const searchActions = alert && (
    <Tooltip title={changeable ? "" : "You need Manage Channels in its channel"}>
      <span style={{ display: "inline-flex", gap: 8 }}>
        <Button size="small" variant="outlined" startIcon={<StorefrontOutlined />} disabled={!changeable}
          onClick={() => { setInfoOpen(false); setMarketplaces(alert); }}>Marketplaces to check</Button>
        <Button size="small" color="error" variant="outlined" startIcon={<DeleteOutlined />} disabled={!changeable}
          onClick={() => { setInfoOpen(false); setUnregistering(alert); }}>Unregister</Button>
      </span>
    </Tooltip>
  );
  const listingTotals = guildId && alerts.data ? alerts.data.totals.guilds[guildId] ?? NO_TOTALS : undefined;

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
        canChange={changeable} actions={searchActions} />;
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
      return <SearchesView guildId={guildId} searches={serverSearches} channels={channels.data}
        filter={place.searchFilter} onFilterChange={(searchFilter) => navigate({ searchFilter })}
        onAdd={() => setAdding({ channelId: null })}
        onOpen={(item) => go({ alertId: item.id })} onOpenChannel={(channelId) => go({ channelId, alertId: null })}
        onUnregister={setUnregistering} />;
    }
    if (view === "listings") {
      return <ServerListingsView guildId={guildId} guildName={guildName} totals={listingTotals} draft={draft} filters={filters}
        onFilters={setFilters} onTestTitle={openTitleTest} searches={alerts.isSuccess ? serverSearches : undefined}
        onOpenSearch={(alertId) => go({ alertId })} onOpenChannel={(channelId) => go({ channelId, alertId: null })} />;
    }
    return <StatusView guildId={guildId} tab={place.statusTab} onTab={(statusTab) => { navigate({ statusTab }); toTop(); }}
      onOpenSearch={(alertId) => go({ alertId })}
      onOpenSearches={(searchFilter) => go({ view: "searches", searchFilter, alertId: null, channelId: null, me: false })} />;
  })();

  const unknownChannel = channels.data?.unknown.find((item) => item.id === place.channelId) ?? null;
  const sections = (() => {
    if (wide) return null;
    if (view === "search" && alert) {
      const tabs = (Object.keys(SEARCH_TABS) as Tab[]).map((tab): Section<Tab> => ({ value: tab, label: SEARCH_TABS[tab],
        icon: SEARCH_ICONS[tab], note: tab === "rules" && draft.edited ? "unpublished changes" : undefined }));
      return <SectionBar label="Search sections" sections={tabs} value={place.tab}
        onChange={(tab) => { navigate({ tab }); toTop(); }} />;
    }
    if (view === "channel" && (channel || unknownChannel)) {
      const available = channelTabs(channel !== null);
      const tabs = available.map((tab): Section<ChannelTab> => ({ value: tab, label: CHANNEL_TABS[tab], icon: CHANNEL_ICONS[tab] }));
      return <SectionBar label="Channel sections" sections={tabs}
        value={available.includes(place.channelTab) ? place.channelTab : "searches"}
        onChange={(channelTab) => { navigate({ channelTab }); toTop(); }} />;
    }
    if (view === "status" && guildId && !guilds.isPending && !guilds.isError) {
      const tabs = (Object.keys(STATUS_TABS) as StatusTab[]).map((tab): Section<StatusTab> => ({ value: tab, label: STATUS_TABS[tab],
        icon: STATUS_ICONS[tab] }));
      return <SectionBar label="Status sections" sections={tabs} value={place.statusTab}
        onChange={(statusTab) => { navigate({ statusTab }); toTop(); }} />;
    }
    return null;
  })();
  // On phones a search's or a server's counts open from the title, instead of a header over the page.
  const info = !wide && ((view === "search" && alert) || view === "listings");

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

  const dashboard = (
    <Box sx={{ display: "flex", height: "100dvh", overflow: "hidden", bgcolor: "background.default" }}>
      <Link href="#main" sx={{ position: "absolute", left: 8, top: -48, zIndex: 2000, bgcolor: "background.paper", p: 1,
        "&:focus": { top: 8 } }}>Skip to content</Link>
      {wide ? lists : (
        <SwipeableDrawer open={navOpen} onOpen={() => setNavOpen(true)} onClose={() => setNavOpen(false)}
          disableSwipeToOpen={iOS} disableDiscovery={iOS} swipeAreaWidth={16}
          slotProps={{ paper: { sx: { width: RAIL_WIDTH + SIDEBAR_WIDTH, maxWidth: "88vw", bgcolor: "surface.sidebar",
            backgroundImage: "none", pt: "env(safe-area-inset-top, 0px)", pb: "env(safe-area-inset-bottom, 0px)",
            pl: "env(safe-area-inset-left, 0px)" } } }}>
          {lists}
        </SwipeableDrawer>
      )}
      {/* The page scrolls between the bar at the top and the sections at the bottom. In landscape it keeps clear of the notch. */}
      <Box sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
        pl: "env(safe-area-inset-left, 0px)", pr: "env(safe-area-inset-right, 0px)" }}>
        <Box component="main" id="main" ref={main} tabIndex={-1} {...(wide ? {} : swipe)}
          sx={{ flex: 1, minHeight: 0, overflowY: "auto", outline: "none", pb: sections ? 0 : "env(safe-area-inset-bottom, 0px)" }}>
          <TopBar icon={heading.icon} title={heading.title} detail={heading.detail} showMenu={!wide} onMenu={() => setNavOpen(true)}
            onHelp={() => setHelpOpen(true)} onTitle={info ? () => setInfoOpen(true) : undefined}
            actions={(view === "search" || view === "listings") && (wide ? (
              <Button size="small" startIcon={<ScienceOutlined />} onClick={() => openTitleTest()} color="inherit" aria-keyshortcuts="t">
                Test a title
              </Button>
            ) : (
              <IconButton aria-label="Test a title" aria-keyshortcuts="t" onClick={() => openTitleTest()}><ScienceOutlined /></IconButton>
            ))} />
          {missing && (
            <Alert severity="warning" sx={{ m: { xs: 2, md: 3 }, mb: 0 }}
              action={<Link component="button" onClick={() => go({ alertId: null, view: "searches" })}>Show the searches</Link>}>
              This search is no longer registered, or it is in a server you no longer manage.
            </Alert>
          )}
          {page}
        </Box>
        {sections}
      </Box>
      {info && (
        <AlertInfoSheet open={infoOpen} onClose={() => setInfoOpen(false)} alert={view === "search" ? alert : null}
          totals={view === "listings" ? listingTotals : undefined} guildName={guildName} draft={draft}
          actions={view === "search" ? searchActions : undefined} />
      )}
      <AddSearchDialog open={adding !== null} channels={channels.data} channelId={adding?.channelId ?? null}
        onClose={() => setAdding(null)} onCreated={(created) => { setAdding(null); go({ alertId: created.id }); }} />
      <MarketplacesDialog alert={marketplaces} onClose={() => setMarketplaces(null)} />
      <UnregisterDialog alert={unregistering} onClose={() => setUnregistering(null)}
        onDone={() => {
          const gone = unregistering;
          setUnregistering(null);
          if (gone && place.alertId === gone.id) go({ alertId: null, channelId: gone.channel_id });
        }} />
      <TitleTestDialog test={titleTest} alert={alert} alerts={home ? alerts.data?.alerts ?? [] : serverSearches}
        onClose={() => setTitleTest((current) => current && { ...current, open: false })} />
      <ShortcutsDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </Box>
  );

  // Every unread badge below, in the lists and on the pages, shows one count of the searches listed here.
  return <SearchUnreadProvider alerts={memberOnly ? undefined : alerts.data?.alerts}>{dashboard}</SearchUnreadProvider>;
}
