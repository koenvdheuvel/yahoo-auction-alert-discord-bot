import Box from "@mui/material/Box";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import type { UseQueryResult } from "@tanstack/react-query";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import type { CandidateQuery } from "../../api/client";
import type { AlertSummary, ArchiveTotals, ReplayResult, RulesResponse } from "../../api/types";
import { visuallyHidden } from "../../lib/a11y";
import type { Place, Tab as TabName } from "../../lib/hooks";
import type { Draft } from "../../lib/useDraft";
import { TOPBAR_HEIGHT } from "../../theme";
import { AlertHeader } from "../AlertHeader";
import type { TitleSeed } from "../TitleTestDialog";
import { ListingsPanel } from "../listings/ListingsPanel";
import { ReplayPanel } from "../replay/ReplayPanel";
import { RulesPanel } from "../rules/RulesPanel";
import { VersionsPanel } from "../versions/VersionsPanel";

export type ListingFilters = Omit<CandidateQuery, "alertId" | "guildId">;

export interface StoredReplay {
  alertId: string;
  /** The draft that was replayed, to tell when the result is out of date. */
  serialized: string;
  ranAt: string;
  result: ReplayResult;
}

const TAB_LABELS: Record<TabName, string> = { listings: "Listings", rules: "Rules", replay: "Replay", versions: "Versions" };

interface Props {
  place: Place;
  navigate: (next: Partial<Place>) => void;
  alert: AlertSummary;
  rules: UseQueryResult<RulesResponse>;
  draft: Draft;
  filters: ListingFilters;
  onFilters: Dispatch<SetStateAction<ListingFilters>>;
  replays: Record<string, StoredReplay>;
  onReplay: (stored: StoredReplay) => void;
  replayRequested: boolean;
  setReplayRequested: (value: boolean) => void;
  onTestTitle: (seed?: TitleSeed) => void;
  /** Whether you have Manage Channels in the search's channel. */
  canChange: boolean;
  actions?: ReactNode;
}

/** One search: its listings, rules, replay and versions. */
export function SearchView(props: Props) {
  const { place, navigate, alert, rules, draft, filters, onFilters, replays, onReplay, replayRequested,
    setReplayRequested, onTestTitle, canChange, actions } = props;
  const panel = (() => {
    switch (place.tab) {
      case "rules":
        return <RulesPanel alert={alert} rules={rules} draft={draft} replay={replays[alert.id] ?? null} canChange={canChange}
          onTestTitle={() => onTestTitle()} onReplay={() => {
            setReplayRequested(true);
            navigate({ tab: "replay" });
          }} />;
      case "replay":
        return <ReplayPanel alert={alert} draft={draft} stored={replays[alert.id] ?? null} onResult={onReplay}
          autoRun={replayRequested} onAutoRun={() => setReplayRequested(false)}
          onEditRules={() => navigate({ tab: "rules" })} />;
      case "versions":
        return <VersionsPanel alert={alert} rules={rules} draft={draft} canChange={canChange}
          onEditRules={() => navigate({ tab: "rules" })} />;
      default:
        return <ListingsPanel alertId={alert.id} guildId={null} filters={filters} onFilters={onFilters} onTestTitle={onTestTitle} />;
    }
  })();

  return (
    <>
      <AlertHeader alert={alert} totals={undefined} guildName={null} draft={draft} actions={actions} />
      <Box sx={{ px: { xs: 2, md: 3 }, borderBottom: 1, borderColor: "divider", position: "sticky", top: TOPBAR_HEIGHT,
        bgcolor: "background.default", zIndex: 3 }}>
        <Tabs value={place.tab} onChange={(_, tab: TabName) => navigate({ tab })} aria-label="Search sections"
          variant="scrollable" allowScrollButtonsMobile>
          {(Object.keys(TAB_LABELS) as TabName[]).map((tab) => (
            <Tab key={tab} value={tab} id={`tab-${tab}`} aria-controls="search-panel"
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
      <Box id="search-panel" role="tabpanel" aria-labelledby={`tab-${place.tab}`} sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
        {panel}
      </Box>
    </>
  );
}

interface ListingsProps {
  guildId: string | null;
  guildName: string | null;
  totals: ArchiveTotals | undefined;
  draft: Draft;
  filters: ListingFilters;
  onFilters: Dispatch<SetStateAction<ListingFilters>>;
  onTestTitle: (seed?: TitleSeed) => void;
}

/** Every saved listing of the server's searches. */
export function ServerListingsView({ guildId, guildName, totals, draft, filters, onFilters, onTestTitle }: ListingsProps) {
  return (
    <>
      <AlertHeader alert={null} totals={totals} guildName={guildName} draft={draft} />
      <Box sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
        <ListingsPanel alertId={null} guildId={guildId} filters={filters} onFilters={onFilters} onTestTitle={onTestTitle} />
      </Box>
    </>
  );
}
