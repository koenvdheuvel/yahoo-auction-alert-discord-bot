import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Drawer from "@mui/material/Drawer";
import Link from "@mui/material/Link";
import { useTheme } from "@mui/material/styles";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useEffect, useState } from "react";

import type { CandidateQuery } from "../api/client";
import { useAlerts, useRules, useSession } from "../api/hooks";
import type { ArchiveTotals, ReplayResult } from "../api/types";
import { visuallyHidden } from "../lib/a11y";
import { isTyping, usePlace, type Tab as TabName } from "../lib/hooks";
import { useDraft } from "../lib/useDraft";
import { AlertHeader } from "./AlertHeader";
import { AlertNav } from "./AlertNav";
import { AppHeader, HEADER_HEIGHT } from "./AppHeader";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { TitleTestDialog, type TitleSeed, type TitleTest } from "./TitleTestDialog";
import { ListingsPanel } from "./listings/ListingsPanel";
import { ReplayPanel } from "./replay/ReplayPanel";
import { RulesPanel } from "./rules/RulesPanel";
import { VersionsPanel } from "./versions/VersionsPanel";

const NAV_WIDTH = 288;

export type ListingFilters = Omit<CandidateQuery, "alertId" | "guildId">;

export interface StoredReplay {
  alertId: string;
  /** The draft that was replayed, to tell when the result is out of date. */
  serialized: string;
  ranAt: string;
  result: ReplayResult;
}

const TAB_LABELS: Record<TabName, string> = { listings: "Listings", rules: "Rules", replay: "Replay", versions: "Versions" };
const NO_TOTALS: ArchiveTotals = { archived_count: 0, unassigned_count: 0 };

export function Workspace() {
  const theme = useTheme();
  const wide = useMediaQuery(theme.breakpoints.up("md"));
  const [place, navigate] = usePlace();
  const guilds = useSession().data?.guilds ?? null;
  const alerts = useAlerts();
  const rules = useRules(place.alertId);
  const draft = useDraft(place.alertId, rules.data);
  const [navOpen, setNavOpen] = useState(false);
  const [titleTest, setTitleTest] = useState<TitleTest | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [replays, setReplays] = useState<Record<string, StoredReplay>>({});
  // "Replay draft" in the Rules tab opens Replay and starts it in one step.
  const [replayRequested, setReplayRequested] = useState(false);
  const [filters, setFilters] = useState<ListingFilters>(
    { search: "", source: "", verdict: "", feedback: "", latest: true });

  const openTitleTest = (seed: TitleSeed = {}) =>
    setTitleTest((current) => ({ id: (current?.id ?? 0) + 1, seed, open: true }));
  const closeTitleTest = () => setTitleTest((current) => current && { ...current, open: false });

  const alert = alerts.data?.alerts.find((item) => item.id === place.alertId) ?? null;
  const missing = place.alertId !== null && alerts.isSuccess && alert === null;
  // People who manage more than one Discord server work in one at a time. A search's own server wins.
  const guildId = guilds && guilds.length > 1
    ? alert?.guild_id ?? (guilds.some((guild) => guild.id === place.guildId) ? place.guildId : guilds[0]!.id)
    : null;
  const guild = guilds?.find((item) => item.id === guildId) ?? null;
  const totals = alerts.data && (guildId ? alerts.data.totals.guilds[guildId] ?? NO_TOTALS : alerts.data.totals);

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

  useEffect(() => {
    document.title = alert ? `${alert.search_query} | Dashboard` : "Dashboard";
  }, [alert]);

  const select = (alertId: string | null) => {
    navigate({ alertId, guildId });
    setNavOpen(false);
  };

  const panel = (() => {
    switch (place.tab) {
      case "rules":
        return <RulesPanel alert={alert} rules={rules} draft={draft}
          replay={place.alertId ? replays[place.alertId] ?? null : null}
          onTestTitle={() => openTitleTest()} onReplay={() => {
            setReplayRequested(true);
            navigate({ tab: "replay" });
          }} />;
      case "replay":
        return <ReplayPanel alert={alert} draft={draft} stored={place.alertId ? replays[place.alertId] ?? null : null}
          onResult={(stored) => setReplays((current) => ({ ...current, [stored.alertId]: stored }))}
          autoRun={replayRequested} onAutoRun={() => setReplayRequested(false)}
          onEditRules={() => navigate({ tab: "rules" })} />;
      case "versions":
        return <VersionsPanel alert={alert} rules={rules} draft={draft} onEditRules={() => navigate({ tab: "rules" })} />;
      default:
        return <ListingsPanel alertId={place.alertId} guildId={guildId} filters={filters} onFilters={setFilters}
          onTestTitle={openTitleTest} />;
    }
  })();

  const navigation = (
    <AlertNav alerts={alerts} selectedId={place.alertId} onSelect={select} guilds={guilds} guildId={guildId}
      total={totals?.archived_count} onGuild={(next) => {
        navigate({ guildId: next, alertId: null });
        setNavOpen(false);
      }} />
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Link href="#main" sx={{ position: "absolute", left: 8, top: -48, zIndex: 2000, bgcolor: "background.paper", p: 1,
        "&:focus": { top: 8 } }}>Skip to content</Link>
      <AppHeader showMenu={!wide} onMenu={() => setNavOpen(true)} onTestTitle={() => openTitleTest()}
        onHelp={() => setHelpOpen(true)} />
      <Drawer
        variant={wide ? "permanent" : "temporary"}
        open={wide || navOpen}
        onClose={() => setNavOpen(false)}
        sx={{ width: wide ? NAV_WIDTH : undefined, flexShrink: 0, zIndex: (theme) => (wide ? theme.zIndex.drawer : theme.zIndex.modal) }}
        slotProps={{ paper: { component: "nav", "aria-label": "Searches", sx: {
          width: NAV_WIDTH, top: wide ? HEADER_HEIGHT : 0, height: wide ? `calc(100% - ${HEADER_HEIGHT}px)` : "100%",
          borderRightColor: "divider", bgcolor: "background.default" } } }}
      >
        {navigation}
      </Drawer>
      <Box component="main" id="main" tabIndex={-1} sx={{ flex: 1, minWidth: 0, pt: `${HEADER_HEIGHT}px`, outline: "none" }}>
        {missing && (
          <Alert severity="warning" sx={{ m: 3, mb: 0 }} action={<Link component="button" onClick={() => select(null)}>Show all listings</Link>}>
            This search is no longer registered, or it is in a server you no longer manage.
          </Alert>
        )}
        <AlertHeader alert={alert} totals={totals} guildName={guild?.name ?? null} draft={draft} />
        <Box sx={{ px: { xs: 2, md: 3 }, borderBottom: 1, borderColor: "divider", position: "sticky",
          top: HEADER_HEIGHT, bgcolor: "background.default", zIndex: 3 }}>
          <Tabs value={place.tab} onChange={(_, tab: TabName) => navigate({ tab })} aria-label="Workspace sections"
            variant="scrollable" allowScrollButtonsMobile>
            {(Object.keys(TAB_LABELS) as TabName[]).map((tab) => (
              <Tab key={tab} value={tab} id={`tab-${tab}`} aria-controls="workspace-panel"
                label={tab === "rules" && draft.edited ? (
                  <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 0.75 }}>
                    Rules
                    <Box component="span" sx={{ width: 7, height: 7, borderRadius: "50%", bgcolor: "text.primary" }} />
                    <Box component="span" sx={visuallyHidden}>(unpublished changes)</Box>
                  </Box>
                ) : TAB_LABELS[tab]} />
            ))}
          </Tabs>
        </Box>
        <Box id="workspace-panel" role="tabpanel" aria-labelledby={`tab-${place.tab}`} sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
          {panel}
        </Box>
      </Box>
      <TitleTestDialog test={titleTest} alert={alert} draft={draft} onClose={closeTitleTest} />
      <ShortcutsDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </Box>
  );
}
