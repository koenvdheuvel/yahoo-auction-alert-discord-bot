import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuildStatus, SearchStatus } from "../../api/types";
import { alertSummary } from "../../test/fixtures";
import { setPhone } from "../../test/screen";
import { theme } from "../../theme";
import { StatusView } from "./StatusView";

const NOW = Math.floor(Date.now() / 1000);
const search = (id: string, query: string, extra: Partial<SearchStatus> = {}): SearchStatus => ({
  ...alertSummary(id, "201", query), channel_name: "posters-yahoo",
  checks: [{ source: "mercari", outcome: "success", finished_at: NOW - 300, duration_seconds: 2, error: null }],
  backlog: { pending: 0, failed: 0, oldest_pending_seconds: null }, ...extra,
});
const FAILING = { checks: [{ source: "mercari" as const, outcome: "error" as const, finished_at: NOW - 300, duration_seconds: 2, error: "HTTP 503" }] };
const STATUS: GuildStatus = {
  bot_running: true,
  bot: { ready: true, discord_connected: true, database_available: true, failed_worker: null, last_poll_at: NOW - 300,
    last_success_at: NOW - 300, started_at: NOW - 3600, interval_seconds: 1800, sources: { mercari: NOW - 300 } },
  enabled_sources: ["mercari"],
  interval_seconds: 1800,
  searches: [
    search("1", "BABYMETAL poster", { ...FAILING, backlog: { pending: 2, failed: 1, oldest_pending_seconds: 600 } }),
    ...["Two", "Three", "Four", "Five"].map((name, index) => search(String(index + 2), `Search ${name}`, FAILING)),
    search("9", "Healthy"),
  ],
  totals: { searches: 6, pending: 2, failed: 1 },
};

function show(status: GuildStatus = STATUS) {
  const fetch = vi.fn(() => Promise.resolve(Response.json(status)));
  vi.stubGlobal("fetch", fetch);
  const onOpenSearch = vi.fn();
  const onOpenSearches = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <StatusView guildId="11" tab="overview" onTab={vi.fn()} onOpenSearch={onOpenSearch} onOpenSearches={onOpenSearches} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { fetch, onOpenSearch, onOpenSearches };
}

afterEach(() => vi.unstubAllGlobals());

describe("StatusView overview", () => {
  it("separates the bot's health from this server's queues, and lists no table of searches", async () => {
    const { fetch } = show();
    expect(await screen.findByRole("heading", { name: "Bot health" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "This server" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // The overview fetches the status only; graphs load on their own tab.
    expect(fetch.mock.calls.every((call) => String((call as unknown[])[0]).endsWith("/status"))).toBe(true);
  });

  it("opens the matching Searches filter from a queue card and from a problem", async () => {
    const user = userEvent.setup();
    const { onOpenSearch, onOpenSearches } = show();
    await user.click(await screen.findByRole("button", { name: /^Failed deliveries: 1/ }));
    expect(onOpenSearches).toHaveBeenLastCalledWith("failed");
    await user.click(screen.getByRole("button", { name: /^Pending deliveries: 2/ }));
    expect(onOpenSearches).toHaveBeenLastCalledWith("pending");
    await user.click(screen.getByRole("button", { name: /^Searches with check errors: 5/ }));
    expect(onOpenSearches).toHaveBeenLastCalledWith("errors");
    await user.click(screen.getByRole("button", { name: "Show in Searches: Check errors" }));
    expect(onOpenSearches).toHaveBeenLastCalledWith("errors");
    await user.click(screen.getAllByRole("button", { name: "BABYMETAL poster" })[0]!);
    expect(onOpenSearch).toHaveBeenCalledWith("1");
  });

  it("names only a few searches of a problem and counts the rest", async () => {
    show();
    expect(await screen.findByText("and 2 more")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Healthy" })).not.toBeInTheDocument();
    expect(screen.getAllByText(/Mercari: HTTP 503/).length).toBe(3);
  });

  it("shows the queues without a bot, and does not claim that checks passed", async () => {
    show({ ...STATUS, bot_running: false, bot: null, searches: STATUS.searches.map((item) => ({ ...item, checks: null })) });
    expect(await screen.findByText(/The bot does not run with this dashboard/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Failed deliveries: 1/ })).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.queryByText(/Every search passed/)).not.toBeInTheDocument();
  });

  it("opens queue help on a phone without navigating away", async () => {
    setPhone();
    const user = userEvent.setup();
    const { onOpenSearches } = show();
    await user.click(await screen.findByRole("button", { name: "About Pending deliveries" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(onOpenSearches).not.toHaveBeenCalled();
  });
});
