import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlertSummary, Facets } from "../../api/types";
import { DEFAULT_LISTING_FILTERS, type ListingFilters } from "../../lib/listingFilters";
import { FilterBar, type ScopeFilter } from "./FilterBar";
import { setPhone } from "../../test/screen";

const FILTERS: ListingFilters = DEFAULT_LISTING_FILTERS;
const FACETS: Facets = { verdict: { accepted: 318, filtered: 80, review: 0 }, channel: [
  { id: "20", name: "posters", count: 300 }, { id: "21", name: null, count: 90 }, { id: "30", name: "retired", count: 8 }] };

function show(filters: Partial<ListingFilters> = {}) {
  const onFilters = vi.fn();
  render(<FilterBar filters={{ ...FILTERS, ...filters }} onFilters={onFilters} facets={FACETS} searchRef={{ current: null }} />);
  return onFilters;
}

function search(id: string, query: string, channelId: string, channelName: string | null): AlertSummary {
  return { id, channel_id: channelId, guild_id: "9", channel_name: channelName, search_query: query, archived_count: 1, listing_count: 1,
    accepted_count: 1, filtered_count: 0, review_count: 0, last_seen_at: null, latest_candidate_id: null, active_version_id: null,
    sources: ["mercari"] };
}

const SEARCHES = [search("5", "BABYMETAL towel", "20", "posters"), search("6", "Toy towel", "21", null),
  search("7", "BABYMETAL shirt", "20", "posters")];

function showScope(scope: Partial<ScopeFilter> = {}) {
  const onChange = vi.fn();
  render(<FilterBar filters={FILTERS} onFilters={vi.fn()} facets={FACETS} searchRef={{ current: null }}
    scope={{ searches: SEARCHES, alertId: "", channelId: "", onChange, ...scope }} />);
  return onChange;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FilterBar on a phone", () => {
  it("picks a decision from a sheet that shows each one's count", async () => {
    setPhone();
    const user = userEvent.setup();
    const onFilters = show();

    await user.click(screen.getByRole("button", { name: "Decision: Any decision" }));
    const sheet = screen.getByRole("dialog", { name: "Decision" });
    const rows = within(sheet).getAllByRole("menuitemradio");
    expect(rows.map((row) => row.textContent)).toEqual(["Any decision398", "Allowed318", "Filtered80", "Needs review0"]);
    expect(rows[0]).toHaveAttribute("aria-checked", "true");

    await user.click(rows[2]!);
    expect(onFilters).toHaveBeenCalledWith({ ...FILTERS, verdict: "filtered" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the current choices on the chips and turns earlier decisions on and off", async () => {
    setPhone();
    const user = userEvent.setup();
    const onFilters = show({ source: "mercari", verdict: "filtered" });

    expect(screen.getByRole("button", { name: "Decision: Filtered (80)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Marketplace: Mercari" }));
    const sheet = screen.getByRole("dialog", { name: "Marketplace" });
    expect(within(sheet).getByRole("menuitemradio", { name: "Mercari" })).toHaveAttribute("aria-checked", "true");
    await user.click(within(sheet).getByRole("menuitemradio", { name: "All marketplaces" }));
    expect(onFilters).toHaveBeenLastCalledWith({ ...FILTERS, verdict: "filtered", source: "" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    const earlier = screen.getByRole("button", { name: "Earlier decisions" });
    expect(earlier).toHaveAttribute("aria-pressed", "false");
    await user.click(earlier);
    expect(onFilters).toHaveBeenLastCalledWith({ ...FILTERS, source: "mercari", verdict: "filtered", latest: false });
  });

  it("clears the search with one tap", async () => {
    setPhone();
    const user = userEvent.setup();
    const onFilters = show({ search: "towel" });

    await user.click(screen.getByRole("button", { name: "Clear the search" }));
    expect(onFilters).toHaveBeenCalledWith(FILTERS);
  });
});

describe("FilterBar on a desktop", () => {
  it("keeps the decisions as buttons with their counts", () => {
    show();
    const decisions = screen.getByRole("group", { name: "Decision" });
    expect(within(decisions).getByRole("button", { name: /^Allowed\s*318$/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear the search" })).toBeNull();
  });
});

describe("FilterBar search and channel filters", () => {
  it("offers the server's channels from its searches and its archive, also those whose searches are gone", async () => {
    setPhone();
    const user = userEvent.setup();
    showScope();

    await user.click(screen.getByRole("button", { name: "Channel: All channels" }));
    const rows = within(screen.getByRole("dialog", { name: "Channel" })).getAllByRole("menuitemradio");
    expect(rows.map((row) => row.textContent)).toEqual(["All channels398", "#posters300", "#retired8", "Channel …2190"]);
  });

  it("narrows the searches to the picked channel, and drops a picked search that is not in a new channel", async () => {
    setPhone();
    const user = userEvent.setup();
    const onChange = showScope({ alertId: "6", channelId: "21" });

    await user.click(screen.getByRole("button", { name: "Search: Toy towel" }));
    const searches = within(screen.getByRole("dialog", { name: "Search" })).getAllByRole("menuitemradio");
    expect(searches.map((row) => row.textContent)).toEqual(["All searches", "Toy towel"]);
    await user.click(searches[0]!);
    expect(onChange).toHaveBeenLastCalledWith({ alertId: "", channelId: "21" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Channel: Channel …21" }));
    await user.click(within(screen.getByRole("dialog", { name: "Channel" })).getByRole("menuitemradio", { name: /#posters/ }));
    expect(onChange).toHaveBeenLastCalledWith({ alertId: "", channelId: "20" });
  });

  it("keeps a picked search when its own channel is picked", async () => {
    setPhone();
    const user = userEvent.setup();
    const onChange = showScope({ alertId: "5" });

    await user.click(screen.getByRole("button", { name: "Channel: All channels" }));
    await user.click(within(screen.getByRole("dialog", { name: "Channel" })).getByRole("menuitemradio", { name: /#posters/ }));
    expect(onChange).toHaveBeenLastCalledWith({ alertId: "5", channelId: "20" });
  });

  it("has no search or channel filter for one search's own listings", () => {
    show();
    expect(screen.queryByRole("combobox", { name: "Channel" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Search" })).toBeNull();
  });
});
