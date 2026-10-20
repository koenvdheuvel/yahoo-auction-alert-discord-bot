import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuildGraphs, TablePanel, TimeseriesPanel } from "../../api/types";
import { theme } from "../../theme";
import { GraphsSection } from "./GraphsSection";

// jsdom has no layout, so the chart is a stand-in that lists what it was asked to draw.
vi.mock("./TimeseriesChart", () => ({
  default: ({ panel }: { panel: TimeseriesPanel }) => <div data-testid="chart">{panel.series.length} series</div>,
}));

const base = { unit: "short", decimals: null, scope: "bot", error: null, description: "" } as const;
const GRAPHS: GuildGraphs = {
  enabled: true, range: "24h", ranges: ["1h", "6h", "24h", "7d"], start: 0, end: 720, step: 720, times: [0, 720],
  warning: null,
  sections: [
    { title: "Polling", panels: [
      { ...base, id: 14, title: "Checks by source", description: "Counts every check.", kind: "timeseries", style: "bars", stacked: true,
        series: [{ legend: "{{source}}", labels: { source: "mercari" }, values: [1, null] }] },
      { ...base, id: 15, title: "Broken panel", kind: "timeseries", style: "line", stacked: false, series: [], error: "The query failed." },
    ] },
    { title: "Searches", panels: [
      { ...base, id: 19, title: "Checks per search", scope: "server", kind: "table",
        columns: [{ key: "search_query", title: "Search" }, { key: "value", title: "Checks" }],
        rows: [{ labels: { alert_id: "17", search_query: "BABYMETAL" }, value: 48 }] },
    ] },
  ],
};

function show(answer: GuildGraphs = GRAPHS, channels: Record<string, string> = {}) {
  const fetch = vi.fn((_path: string) => Promise.resolve(Response.json(answer)));
  vi.stubGlobal("fetch", fetch);
  const onOpenSearch = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={client}>
        <GraphsSection guildId="11" channels={channels} onOpenSearch={onOpenSearch} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { fetch, onOpenSearch };
}

afterEach(() => vi.unstubAllGlobals());

describe("GraphsSection", () => {
  it("explains that graphs need Prometheus when the bot has none", async () => {
    show({ ...GRAPHS, enabled: false, start: null, end: null, step: null, times: [], sections: [] });
    expect(await screen.findByText(/Graphs need Prometheus/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Time range" })).not.toBeInTheDocument();
  });

  it("shows a panel's description in its help tip", async () => {
    show();
    await userEvent.hover(await screen.findByRole("button", { name: "About Checks by source" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Counts every check.");
  });

  it("keeps the other panels when one panel's query failed", async () => {
    show();
    expect(await screen.findByText("The query failed.")).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toHaveTextContent("1 series");
    expect(screen.getByText("BABYMETAL")).toBeInTheDocument();
  });

  it("tells searches with the same text apart by channel and opens the one picked", async () => {
    const table: TablePanel = { ...base, id: 19, title: "Checks per search", scope: "server", kind: "table",
      columns: [{ key: "search_query", title: "Search" }, { key: "value", title: "Checks" }],
      rows: [{ labels: { alert_id: "17", search_query: "BABYMETAL" }, value: 48 },
        { labels: { alert_id: "18", search_query: "BABYMETAL" }, value: 5 }] };
    const { onOpenSearch } = show({ ...GRAPHS, sections: [{ title: "Searches", panels: [table] }] }, { 17: "#posters", 18: "#vinyl" });
    const rows = within(await screen.findByRole("table", { name: "Checks per search" })).getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("#posters")).toBeInTheDocument();
    await userEvent.click(within(rows[1]!).getByRole("button", { name: "BABYMETAL" }));
    expect(onOpenSearch).toHaveBeenCalledWith("18");
  });

  it("asks for the range that was picked", async () => {
    const { fetch } = show();
    await userEvent.click(await screen.findByRole("button", { name: "6h" }));
    expect(fetch.mock.calls.some(([path]) => path === "/api/guilds/11/graphs?range=6h")).toBe(true);
  });
});
