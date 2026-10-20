import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { lazy, Suspense } from "react";

import type { GraphPanel, GraphRange } from "../../api/types";
import { HelpTip } from "../common/HelpTip";
import { GraphTable } from "./GraphTable";

// The chart library is big, so it loads only when a graph has data to draw.
const TimeseriesChart = lazy(() => import("./TimeseriesChart"));

const SCOPES = {
  server: ["This server", "Counts only this server's searches."],
  bot: ["All servers", "Counts the whole bot, every server together."],
} as const;

interface Props {
  panel: GraphPanel;
  times: number[];
  range: GraphRange;
  /** The channel of each search whose text another search has too, by alert ID. */
  channels: Record<string, string>;
  onOpenSearch: (alertId: string) => void;
}

function Body({ panel, times, range, channels, onOpenSearch }: Props) {
  if (panel.kind === "table") {
    return panel.rows.length === 0 ? <Empty /> : <GraphTable panel={panel} channels={channels} onOpenSearch={onOpenSearch} />;
  }
  if (panel.series.length === 0) return <Empty />;
  return (
    <Suspense fallback={<Skeleton variant="rounded" height={220} />}>
      <TimeseriesChart panel={panel} times={times} range={range} channels={channels} />
    </Suspense>
  );
}

function Empty() {
  return <Typography variant="body2" color="textSecondary">No data in this range.</Typography>;
}

/** One graph: its title, what it explains, whose searches it counts, and the data. */
export function GraphPanelCard({ panel, times, range, channels, onOpenSearch }: Props) {
  const [scope, scopeHelp] = SCOPES[panel.scope];
  return (
    <Paper sx={{ p: 2, bgcolor: "background.paper", minWidth: 0 }}>
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, mb: 1 }}>
        <Typography variant="subtitle2" component="h4" sx={{ flex: 1, minWidth: 0 }}>
          {panel.title}
          {panel.description && <HelpTip title={panel.title} text={panel.description} />}
        </Typography>
        <Tooltip title={scopeHelp}>
          <Chip variant="outlined" label={scope} sx={{ flexShrink: 0 }} />
        </Tooltip>
      </Box>
      {panel.error && <Alert severity="warning" sx={{ py: 0, mb: 1 }}>{panel.error}</Alert>}
      {!panel.error && <Body panel={panel} times={times} range={range} channels={channels} onOpenSearch={onOpenSearch} />}
    </Paper>
  );
}
