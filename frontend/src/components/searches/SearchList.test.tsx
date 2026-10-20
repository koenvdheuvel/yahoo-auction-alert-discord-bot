import { ThemeProvider } from "@mui/material/styles";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SearchStatus } from "../../api/types";
import { SearchUnreadContext, type SearchUnreadStates } from "../../lib/unreadCounts";
import { alertSummary } from "../../test/fixtures";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import type { LiveStatus } from "./liveStatus";
import { SearchList } from "./SearchList";

const ALERTS = [
  { ...alertSummary("1", "201", "BABYMETAL poster"), channel_name: "posters-yahoo", review_count: 2 },
  { ...alertSummary("2", "204", "Staff only"), channel_name: "staff" },
];

function show(extra: Partial<ComponentProps<typeof SearchList>> = {}, unread: SearchUnreadStates = new Map()) {
  const onOpen = vi.fn();
  const onOpenChannel = vi.fn();
  const onUnregister = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <SearchUnreadContext.Provider value={unread}>
        <SearchList alerts={ALERTS} showChannel canChange={(alert) => alert.id === "1"} onOpen={onOpen}
          onOpenChannel={onOpenChannel} onUnregister={onUnregister} {...extra} />
      </SearchUnreadContext.Provider>
    </ThemeProvider>,
  );
  return { onOpen, onOpenChannel, onUnregister };
}

const NOW = Math.floor(Date.now() / 1000);

/** Live status for these searches: "1" failed its Mercari check and has a failed post; "2" is fine but has posts waiting. */
function liveStatus(botRunning = true): LiveStatus {
  const status = (alert: (typeof ALERTS)[number], checks: SearchStatus["checks"], backlog: SearchStatus["backlog"]): SearchStatus =>
    ({ ...alert, checks: botRunning ? checks : null, backlog });
  return { kind: "ready", botRunning, searches: new Map([
    ["1", status(ALERTS[0]!, [{ source: "mercari", outcome: "error", finished_at: NOW - 300, duration_seconds: 2, error: "HTTP 503" }],
      { pending: 0, failed: 2, oldest_pending_seconds: null })],
    ["2", status(ALERTS[1]!, [{ source: "mercari", outcome: "success", finished_at: NOW - 60, duration_seconds: 1, error: null }],
      { pending: 3, failed: 0, oldest_pending_seconds: 600 })],
  ]) };
}

/** Thirty searches in one channel, "Search 01" to "Search 30". */
const MANY = Array.from({ length: 30 }, (_, index) => alertSummary(String(100 + index), "201", `Search ${String(index + 1).padStart(2, "0")}`));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("SearchList on a phone", () => {
  it("shows each search as a card that opens it, with Unregister where you may change it", async () => {
    setPhone();
    const user = userEvent.setup();
    const { onOpen, onUnregister } = show();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const card = screen.getByRole("button", { name: "BABYMETAL poster" });
    await user.click(card);
    expect(onOpen).toHaveBeenCalledWith(ALERTS[0]);
    await user.click(screen.getByRole("button", { name: "Unregister BABYMETAL poster" }));
    expect(onUnregister).toHaveBeenCalledWith(ALERTS[0]);
    // Without Manage Channels there is no button, and the card says why instead of a tooltip.
    expect(screen.queryByRole("button", { name: "Unregister Staff only" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Staff only" }))
      .toHaveAccessibleDescription(/You need Manage Channels in its channel to unregister it/);
  });

  it("opens the search's actions on a long press, like a message in Discord's app", () => {
    setPhone();
    vi.useFakeTimers();
    const { onOpen, onOpenChannel } = show();
    const card = screen.getByRole("button", { name: "Staff only" });
    fireEvent.touchStart(card, { touches: [{ clientX: 10, clientY: 10 }] });
    act(() => { vi.advanceTimersByTime(500); });
    // Lifting the finger is cancelled, so the browser sends no click to the sheet that just opened under it.
    expect(fireEvent.touchEnd(card, { touches: [] })).toBe(false);
    fireEvent.click(card);
    expect(onOpen).not.toHaveBeenCalled();

    const sheet = screen.getByRole("dialog", { name: "Staff only" });
    expect(within(sheet).getByRole("button", { name: "Unregister" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(within(sheet).getByRole("button", { name: "Open #staff" }));
    expect(onOpenChannel).toHaveBeenCalledWith("204");
  });
});

describe("SearchList on a larger screen", () => {
  it("keeps the table", () => {
    show();
    expect(screen.getByRole("table", { name: "Searches" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unregister Staff only" })).toBeDisabled();
  });
});

describe("SearchList inventory", () => {
  it("has Unread and Needs review columns and tells a count that is on its way from zero", () => {
    show({}, new Map([["1", { kind: "count", count: 4 }], ["2", { kind: "loading" }]]));
    const table = screen.getByRole("table", { name: "Searches" });
    for (const name of ["Unread", "Needs review"]) expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    expect(within(table).getByText("4")).toBeInTheDocument();
    expect(within(table).getByText("…")).toBeInTheDocument();
    expect(screen.getByText("Counting unread listings for 1 search…")).toBeInTheDocument();
  });


  it("leaves out the live columns and filters without status, instead of showing zeros", () => {
    show();
    expect(screen.queryByRole("columnheader", { name: "Last checks" })).not.toBeInTheDocument();
    const filters = within(screen.getByRole("group", { name: "Quick filters" }));
    expect(filters.queryByRole("button", { name: /Check errors/ })).not.toBeInTheDocument();
    expect(filters.getByRole("button", { name: /Needs review/ })).toBeInTheDocument();
  });

  it("filters by words, channel and quick filters, and clears them", async () => {
    const user = userEvent.setup();
    show({ live: liveStatus() });
    await user.click(screen.getByRole("button", { name: "Check errors 1" }));
    let table = screen.getByRole("table", { name: "Searches" });
    expect(within(table).getByRole("button", { name: "BABYMETAL poster" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: "Staff only" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.click(screen.getByRole("button", { name: "Pending deliveries 1" }));
    table = screen.getByRole("table", { name: "Searches" });
    expect(within(table).getByRole("button", { name: "Staff only" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: "BABYMETAL poster" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.type(screen.getByRole("searchbox", { name: "Filter by name or channel" }), "staff");
    expect(screen.getByText("Showing 1 of 2 searches")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "nothing like it");
    expect(screen.getByText("No searches match these filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("filters to the searches with unread listings", async () => {
    const user = userEvent.setup();
    show({}, new Map([["2", { kind: "count", count: 5 }]]));
    await user.click(screen.getByRole("button", { name: "Unread 1" }));
    const table = screen.getByRole("table", { name: "Searches" });
    expect(within(table).getByRole("button", { name: "Staff only" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: "BABYMETAL poster" })).not.toBeInTheDocument();
  });

  it("reports a filter that needs live status instead of listing nothing while it loads or fails", () => {
    show({ live: { kind: "loading" }, filter: "errors", onFilterChange: vi.fn() });
    expect(screen.getByText("Loading the live status…")).toBeInTheDocument();
    expect(screen.queryByText("No searches match these filters.")).not.toBeInTheDocument();
  });

  it("says check errors are unknown when the bot does not run", () => {
    show({ live: liveStatus(false), filter: "errors", onFilterChange: vi.fn() });
    expect(screen.getByText(/does not run with this dashboard, so check errors are not known here/)).toBeInTheDocument();
  });

  it("follows the filter the page keeps in its address and reports changes to it", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    show({ live: liveStatus(), filter: "failed", onFilterChange });
    expect(screen.getByRole("button", { name: "Failed deliveries 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Staff only" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Failed deliveries 1" }));
    expect(onFilterChange).toHaveBeenCalledWith(null);
  });

  it("starts a filtered result on the first page and never leaves you on a page that is gone", async () => {
    const user = userEvent.setup();
    show({ alerts: MANY, showChannel: false, onUnregister: undefined });
    expect(screen.getAllByRole("row")).toHaveLength(26);
    await user.click(screen.getByRole("button", { name: "Go to next page" }));
    expect(screen.getAllByRole("row")).toHaveLength(6);
    await user.type(screen.getByRole("searchbox", { name: "Filter by name" }), "Search 0");
    expect(screen.getByRole("button", { name: "Search 01" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(10);
  });

  it("sorts by a column, newest or biggest first", async () => {
    const user = userEvent.setup();
    show({ alerts: [ALERTS[0]!, { ...ALERTS[1]!, listing_count: 40 }] });
    await user.click(screen.getByRole("button", { name: "Listings" }));
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByRole("button", { name: "Staff only" })).toBeInTheDocument();
  });
});

describe("SearchList on a phone's inventory", () => {
  it("keeps the filters, sorting and live checks on the cards", async () => {
    setPhone();
    const user = userEvent.setup();
    show({ live: liveStatus() });
    expect(screen.getByRole("searchbox", { name: "Filter by name or channel" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Sort by" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "BABYMETAL poster" }))
      .toHaveAccessibleDescription(/Mercari Error.*Mercari: HTTP 503.*Posts and DMs: 2 failed/);
    await user.click(screen.getByRole("button", { name: "Pending deliveries 1" }));
    expect(screen.queryByRole("button", { name: "BABYMETAL poster" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Staff only" })).toHaveAccessibleDescription(/Posts and DMs: 3 waiting, oldest 10 min/);
  });
});
