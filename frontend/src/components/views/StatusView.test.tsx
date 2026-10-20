import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GuildStatus } from "../../api/types";
import { alertSummary } from "../../test/fixtures";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import { StatusView } from "./StatusView";

const NOW = Math.floor(Date.now() / 1000);
const STATUS: GuildStatus = {
  bot_running: true,
  bot: { ready: true, discord_connected: true, database_available: true, failed_worker: null, last_poll_at: NOW - 300,
    last_success_at: NOW - 300, started_at: NOW - 3600, interval_seconds: 1800, sources: { mercari: NOW - 300 } },
  enabled_sources: ["mercari"],
  interval_seconds: 1800,
  searches: [{
    ...alertSummary("1", "201", "BABYMETAL poster"), channel_name: "posters-yahoo",
    checks: [{ source: "mercari", outcome: "error", finished_at: NOW - 300, duration_seconds: 2, error: "HTTP 503" }],
    backlog: { pending: 2, failed: 1, oldest_pending_seconds: 600 },
  }],
  totals: { searches: 1, pending: 2, failed: 1 },
};

function show() {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json(STATUS))));
  const onOpenSearch = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <StatusView guildId="11" onOpenSearch={onOpenSearch} onOpenChannel={vi.fn()} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { onOpenSearch };
}

afterEach(() => vi.unstubAllGlobals());

describe("StatusView", () => {
  it("shows each search as a card on a phone, with what failed written out", async () => {
    setPhone();
    const user = userEvent.setup();
    const { onOpenSearch } = show();
    const card = await screen.findByRole("button", { name: "BABYMETAL poster" });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // A desktop shows the error when the pointer rests on the check; a phone shows it on the card.
    expect(card).toHaveAccessibleDescription(/Mercari Error.*Mercari: HTTP 503.*Posts and DMs: 2 waiting, 1 failed, oldest 10 min/);
    await user.click(card);
    expect(onOpenSearch).toHaveBeenCalledWith("1");
  });

  it("keeps the table on a larger screen", async () => {
    show();
    expect(await screen.findByRole("table", { name: "Search status" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "BABYMETAL poster" })).toBeInTheDocument();
  });
});
