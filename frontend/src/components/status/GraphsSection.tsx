import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Skeleton from "@mui/material/Skeleton";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { useGuildGraphs } from "../../api/hooks";
import type { GraphRange } from "../../api/types";
import { LoadError } from "../common/Feedback";
import { HelpTip } from "../common/HelpTip";
import { GraphPanelCard } from "./GraphPanelCard";

const HELP = "The main graphs of the bot's Grafana dashboard, drawn from the same Prometheus data and explained the same way. "
  + "Graphs marked This server only count this server's searches; the others cover the whole bot, every server together.";

interface Props {
  guildId: string;
  /** The channel of each search whose text another search has too, by alert ID (sharedSearchChannels). */
  channels: Record<string, string>;
  onOpenSearch: (alertId: string) => void;
}

/** The bot's main Grafana graphs for the server being viewed. */
export function GraphsSection({ guildId, channels, onOpenSearch }: Props) {
  const [range, setRange] = useState<GraphRange>("24h");
  const graphs = useGuildGraphs(guildId, range);
  const data = graphs.data;
  return (
    <Box>
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>
        Graphs
        <HelpTip title="Graphs" text={HELP} />
      </Typography>
      {graphs.isPending ? <Skeleton variant="rounded" height={260} />
        : graphs.isError ? <LoadError error={graphs.error} what="The graphs" onRetry={() => void graphs.refetch()} />
          : !data?.enabled ? (
            <Alert severity="info" variant="outlined">
              Graphs need Prometheus. When the bot's operator sets PROMETHEUS_URL, the main graphs of the bot's Grafana
              dashboard appear here.
            </Alert>
          ) : (
            <>
              <ToggleButtonGroup exclusive size="small" aria-label="Time range" value={range} sx={{ mb: 2 }}
                onChange={(_, next: GraphRange | null) => next && setRange(next)}>
                {data.ranges.map((entry) => (
                  <ToggleButton key={entry} value={entry}>{entry}</ToggleButton>
                ))}
              </ToggleButtonGroup>
              {data.warning && <Alert severity="warning" sx={{ mb: 2 }}>{data.warning}</Alert>}
              <Box sx={{ opacity: graphs.isPlaceholderData ? 0.6 : 1, transition: "opacity 0.15s" }}>
                {data.sections.map((section) => (
                  <Box key={section.title} component="section" sx={{ mb: 3 }}>
                    <Typography variant="subtitle1" component="h3" sx={{ mb: 1 }}>{section.title}</Typography>
                    <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", lg: "repeat(2, 1fr)" } }}>
                      {section.panels.map((panel) => (
                        <GraphPanelCard key={panel.id} panel={panel} times={data.times} range={data.range} channels={channels}
                          onOpenSearch={onOpenSearch} />
                      ))}
                    </Box>
                  </Box>
                ))}
              </Box>
            </>
          )}
    </Box>
  );
}
