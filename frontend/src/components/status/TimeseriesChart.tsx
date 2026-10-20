import Box from "@mui/material/Box";
import { useColorScheme, useTheme } from "@mui/material/styles";
import Typography from "@mui/material/Typography";
import { BarChart } from "@mui/x-charts/BarChart";
import { LineChart } from "@mui/x-charts/LineChart";
import { useMemo } from "react";

import type { GraphRange, TimeseriesPanel } from "../../api/types";
import { durationTicks, failureTone, formatGraphValue, labelledBars, seriesNames } from "../../lib/graphs";
import { figures } from "../../theme";

// Colours for series that are not failures, one list per colour scheme. They stay apart from the
// red and amber the failures use.
const PALETTES = {
  dark: ["#7983F5", "#3BC9DB", "#69DB7C", "#C792EA", "#4DABF7", "#A9E34B", "#F783AC", "#9AA3B2"],
  light: ["#4752C4", "#0B7285", "#2B8A3E", "#862E9C", "#1864AB", "#5C940D", "#C2255C", "#5C6370"],
};

export interface TimeseriesChartProps {
  panel: TimeseriesPanel;
  times: number[];
  range: GraphRange;
  /** The channel of each search whose text another search has too, by alert ID. */
  channels: Record<string, string>;
}

const timeFormat = new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit", hour12: false });
const dayFormat = new Intl.DateTimeFormat([], { month: "short", day: "numeric" });
const fullFormat = new Intl.DateTimeFormat([], { dateStyle: "medium", timeStyle: "short" });

function useSeriesColors(panel: TimeseriesPanel): string[] {
  const theme = useTheme();
  const { mode, systemMode } = useColorScheme();
  const scheme = (mode === "system" ? systemMode : mode) === "light" ? "light" : "dark";
  const palette = (theme.vars ?? theme).palette;
  let next = 0;
  return panel.series.map((entry) => {
    const tone = failureTone(entry.labels.outcome);
    if (tone) return palette[tone].main ?? "";
    return PALETTES[scheme][next++ % PALETTES[scheme].length] ?? "";
  });
}

/** A Grafana time series drawn as bars or lines, with a compact legend below the plot. */
export default function TimeseriesChart({ panel, times, range, channels }: TimeseriesChartProps) {
  const names = useMemo(() => seriesNames(panel.title, panel.series, channels), [panel, channels]);
  const colors = useSeriesColors(panel);
  const dates = useMemo(() => times.map((time) => new Date(time * 1000)), [times]);
  const labelled = useMemo(() => labelledBars(times), [times]);
  const format = (value: number | null) => formatGraphValue(value, panel.unit, panel.decimals);
  const series = panel.series.map((entry, index) => ({
    id: String(index),
    label: names[index],
    data: entry.values,
    color: colors[index],
    valueFormatter: format,
    ...(panel.stacked ? { stack: "total" } : {}),
  }));
  const tick = range === "7d" ? dayFormat : timeFormat;
  const xFormatter = (value: Date, context: { location: string }) => (context.location === "tooltip" ? fullFormat : tick).format(value);
  const ticks = panel.unit === "s" ? durationTicks(panel.series, panel.stacked) : null;
  const yAxis = [{ valueFormatter: format, width: 64,
    ...(ticks ? { tickInterval: ticks, min: 0, max: ticks[ticks.length - 1] } : {}) }];
  const common = { height: 220, hideLegend: true, margin: { top: 8, right: 8, bottom: 8, left: 0 }, yAxis, skipAnimation: true,
    slotProps: { tooltip: { trigger: "axis" as const } } };
  return (
    <Box>
      {panel.style === "bars" ? (
        <BarChart {...common} series={series}
          xAxis={[{ scaleType: "band", data: dates, valueFormatter: xFormatter, tickInterval: (_: Date, index: number) => labelled[index] ?? false }]} />
      ) : (
        <LineChart {...common}
          series={series.map((entry) => ({ ...entry, showMark: false, connectNulls: false, area: panel.stacked }))}
          xAxis={[{ scaleType: "time", data: dates, valueFormatter: xFormatter, tickNumber: 6 }]} />
      )}
      <Box component="ul" aria-label="Legend"
        sx={{ m: 0, mt: 0.5, p: 0, listStyle: "none", display: "flex", flexWrap: "wrap", gap: "2px 12px", maxHeight: 72, overflowY: "auto" }}>
        {names.map((name, index) => (
          <Box component="li" key={index} sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0 }}>
            <Box aria-hidden sx={{ width: 10, height: 10, borderRadius: "2px", flexShrink: 0, bgcolor: colors[index] }} />
            <Typography variant="caption" color="textSecondary" noWrap sx={{ maxWidth: 240, ...figures }}>{name}</Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
