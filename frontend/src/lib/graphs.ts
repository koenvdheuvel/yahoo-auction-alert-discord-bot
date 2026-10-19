import type { GraphSeries, SearchStatus } from "../api/types";
import { channelLabel } from "./channels";
import { sourceName } from "./vocabulary";

const number = (digits: Intl.NumberFormatOptions) => new Intl.NumberFormat("en", digits);
const COMPACT = number({ notation: "compact", maximumSignificantDigits: 3 });
const PLAIN = number({ maximumFractionDigits: 3 });

/** A count or plain number: "48", "2.9", "1.23K". A fixed `decimals` keeps that many decimals. */
function compact(value: number, decimals: number | null): string {
  if (decimals === null) return COMPACT.format(value);
  return number({ notation: "compact", minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
}

/** Seconds as a duration that is short to read: ms below 1 s, then s, min and h. */
function duration(seconds: number, decimals: number | null): string {
  const abs = Math.abs(seconds);
  const fixed = (value: number, unit: string) =>
    `${decimals === null ? number({ maximumSignificantDigits: 3 }).format(value) : value.toFixed(decimals)} ${unit}`;
  if (abs === 0) return "0 s";
  if (abs < 1) return fixed(seconds * 1000, "ms");
  if (abs < 60) return fixed(seconds, "s");
  if (abs < 3600) return fixed(seconds / 60, "min");
  return fixed(seconds / 3600, "h");
}

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

function bytes(value: number, decimals: number | null): string {
  let scaled = Math.abs(value);
  let unit = 0;
  while (scaled >= 1024 && unit < BYTE_UNITS.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  const sign = value < 0 ? "-" : "";
  const text = unit === 0 ? number({ maximumFractionDigits: 0 }).format(scaled)
    : decimals === null ? number({ maximumSignificantDigits: 3 }).format(scaled) : scaled.toFixed(decimals);
  return `${sign}${text} ${BYTE_UNITS[unit]}`;
}

/** A value in the Grafana unit the panel uses. Unknown units show the plain number. */
export function formatGraphValue(value: number | null | undefined, unit: string, decimals: number | null = null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  switch (unit) {
    case "s": return duration(value, decimals);
    case "reqps": return `${compact(value, decimals)}/s`;
    case "bytes": return bytes(value, decimals);
    case "short":
    case "none": return compact(value, decimals);
    default: return decimals === null ? PLAIN.format(value) : value.toFixed(decimals);
  }
}

/** The table's number column: a whole number unless the panel asks for decimals. A gap is empty. */
export function formatTableValue(value: number | null, decimals: number | null): string {
  if (value === null) return "";
  return number({ maximumFractionDigits: decimals ?? 2, minimumFractionDigits: decimals ?? 0 }).format(value);
}

// Round steps for a duration axis, in seconds, so ticks read 30 s, 1 min or 15 min, not 16.7 min.
const DURATION_STEPS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300,
  600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400];

/**
 * Ticks from 0 at a round duration, at most `most` steps, up to what a graph in seconds draws:
 * its largest value, or its highest stack. Null leaves the ticks to the chart: for no values,
 * values below 0, or more than a few days.
 */
export function durationTicks(series: GraphSeries[], stacked: boolean, most = 4): number[] | null {
  const tops: number[] = [];
  for (const entry of series) {
    for (const [index, value] of entry.values.entries()) {
      if (value === null) continue;
      if (value < 0) return null;
      tops[index] = stacked ? (tops[index] ?? 0) + value : Math.max(tops[index] ?? 0, value);
    }
  }
  const top = tops.reduce((highest, value) => Math.max(highest, value), 0);
  const step = DURATION_STEPS.find((seconds) => top / seconds <= most);
  if (!top || step === undefined) return null;
  return Array.from({ length: Math.ceil(top / step) + 1 }, (_, index) => index * step);
}

// Round lengths of local time between a bar chart's time labels, in seconds.
const LABEL_STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400];

/**
 * Which bars, at these Unix times, get a time label: the first bar of each round length of
 * local time, with at most `most` of them, so labels read 12:00 and 15:00, not 11:36 and 14:48.
 */
export function labelledBars(times: number[], most = 8): boolean[] {
  const step = (times[1] ?? 0) - (times[0] ?? 0);
  if (step <= 0) return times.map(() => true);
  const span = (times[times.length - 1] ?? 0) - (times[0] ?? 0);
  const every = LABEL_STEPS.find((seconds) => span / seconds <= most) ?? 86400;
  return times.map((time) => {
    const date = new Date(time * 1000);
    return (date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds()) % every < step;
  });
}

const WORDS: Record<string, string> = {
  success: "OK", error: "Error", timeout: "Timed out", cancelled: "Cancelled", partial: "Partial",
  new: "New", changed: "Changed", unchanged: "Unchanged", muted: "Muted", unregistered: "Unregistered",
  blacklisted: "Blacklisted", invalid: "Invalid", filter_timeout: "Filter timed out", filtered: "Filtered", review: "Review",
  http_error: "HTTP error", transient_error: "Temporary error", invalid_response: "Invalid response",
  network_error: "Network error", failure: "Failed",
  sent: "Sent", retry: "Retry", failed: "Failed",
  channel: "Channel post", dm: "DM", delete: "Delete",
  search: "Search", detail: "Detail",
};

const FRIENDLY_LABELS: Record<string, true> = { outcome: true, kind: true, operation: true };

/** A label value in words: sources by marketplace name, known words from a map, the rest tidied. */
export function friendlyLabel(name: string, value: string): string {
  if (name === "source") return sourceName(value);
  if (!FRIENDLY_LABELS[name]) return value;
  return WORDS[value] ?? value.replaceAll("_", " ");
}

/** Grafana's legend format with every `{{label}}` replaced by words. */
export function legendName(legend: string, labels: Record<string, string>): string {
  return legend.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) => (labels[name] === undefined ? "" : friendlyLabel(name, labels[name])))
    .replace(/\s+/g, " ").trim();
}

/**
 * The channel of each search whose text another search in the server has too, by alert ID.
 * Graphs name searches by their text, so the channel is what tells these apart.
 */
export function sharedSearchChannels(searches: Pick<SearchStatus, "id" | "search_query" | "channel_id" | "channel_name">[]): Record<string, string> {
  const counts = new Map<string, number>();
  for (const search of searches) counts.set(search.search_query, (counts.get(search.search_query) ?? 0) + 1);
  return Object.fromEntries(searches.filter((search) => (counts.get(search.search_query) ?? 0) > 1)
    .map((search) => [search.id, channelLabel(search.channel_id, search.channel_name)]));
}

/** The names, with `extra(index)` added in brackets to each name that more than one series has. */
function tellApart(names: string[], extra: (index: number) => string | undefined): string[] {
  const counts = new Map<string, number>();
  for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1);
  return names.map((name, index) => {
    const more = (counts.get(name) ?? 0) > 1 ? extra(index) : undefined;
    return more ? `${name} (${more})` : name;
  });
}

const SEARCH_IN_LEGEND = /\{\{\s*search_query\s*\}\}/;

/**
 * One readable name per series: the legend; else the label values; else the panel's title.
 * Series that end up with the same name are told apart by their search, and searches with the
 * same text by their channel, from `channels` (see sharedSearchChannels).
 */
export function seriesNames(title: string, series: GraphSeries[], channels: Record<string, string> = {}): string[] {
  const names = series.map((entry) => {
    const fromLegend = legendName(entry.legend, entry.labels);
    if (fromLegend) return fromLegend;
    const fromLabels = Object.entries(entry.labels).filter(([name]) => name !== "alert_id" && name !== "search_query")
      .map(([name, value]) => friendlyLabel(name, value)).join(" ");
    return fromLabels || title;
  });
  const bySearch = tellApart(names, (index) => {
    const entry = series[index];
    return entry && !SEARCH_IN_LEGEND.test(entry.legend) ? entry.labels.search_query : undefined;
  });
  return tellApart(bySearch, (index) => channels[series[index]?.labels.alert_id ?? ""]);
}

/** Outcomes that mean something went wrong, and how bad. Everything else is not a problem. */
const FAILURES: Record<string, "error" | "warning"> = {
  error: "error", failed: "error", http_error: "error", network_error: "error", invalid_response: "error",
  failure: "error", timeout: "warning", transient_error: "warning", retry: "warning", partial: "warning",
};

export function failureTone(outcome: string | undefined): "error" | "warning" | null {
  return (outcome && FAILURES[outcome]) || null;
}
