import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keys } from "../../api/hooks";
import type { AlertSummary, Candidate, CandidatePage, Session } from "../../api/types";
import { SearchReadOwner } from "../../lib/searchReads";
import { NoticeContext } from "../common/notify";
import { DEFAULT_LISTING_FILTERS, type ListingFilters } from "../../lib/listingFilters";
import { alertSummary } from "../../test/fixtures";
import { ListingsPanel } from "./ListingsPanel";
import { setPhone } from "../../test/screen";

// jsdom does no layout, so it has no scrollIntoView.
Element.prototype.scrollIntoView = () => undefined;

function listing(id: string): Candidate {
  const title = `BABYMETAL towel ${id}`;
  return {
    id, alert_id: "5", channel_id: "20", guild_id: "9", channel_name: "posters", search_query: "BABYMETAL towel", source: "mercari", external_id: `m${id}`,
    title, normalized_title: title.toLowerCase(), payload: { url: `https://jp.mercari.com/item/m${id}`, price: 1500 },
    decision: { verdict: "accepted", normalized_title: title.toLowerCase(), reasons: [] }, verdict: "accepted",
    ruleset_version_id: "4", observation_kind: "listing", origin: "live", incomplete: false,
    observed_at: "2026-10-16T00:00:00Z", last_seen_at: "2026-10-16T00:00:00Z", item_id: `4${id}`, subscribed: false,
  };
}

const PAGE: CandidatePage = {
  items: [listing("1"), listing("2")], total: 2, has_more: false, next_cursor: null,
  facets: { verdict: { accepted: 2, filtered: 0, review: 0 }, channel: [{ id: "20", name: "posters", count: 2 }] },
};

const MEMBER: Session = { authenticated: true, method: "discord", features: { notifications: true, discord_data: true } };

/** Shows two listings with keyboard focus on the first. */
async function showListings({ phone = false, session }: { phone?: boolean; session?: Session } = {}) {
  if (phone) setPhone();
  const fetch = vi.fn(() => Promise.resolve(Response.json(PAGE)));
  vi.stubGlobal("fetch", fetch);
  const notify = vi.fn();
  const client = new QueryClient();
  if (session) client.setQueryData(keys.session, session);
  render(
    <QueryClientProvider client={client}>
      <NoticeContext.Provider value={notify}>
        <ListingsPanel alertId="5" guildId={null} filters={DEFAULT_LISTING_FILTERS}
          onFilters={() => undefined} onTestTitle={() => undefined} />
      </NoticeContext.Provider>
    </QueryClientProvider>,
  );
  const frames = await screen.findAllByRole("listitem");
  act(() => frames[0]!.focus());
  return { frames, fetch, notify };
}

/** Rests a finger on the element until it counts as a long press, then lifts it. False when the lift was cancelled. */
function longPress(element: Element) {
  vi.useFakeTimers();
  fireEvent.touchStart(element, { touches: [{ clientX: 10, clientY: 10 }] });
  act(() => { vi.advanceTimersByTime(500); });
  const lifted = fireEvent.touchEnd(element, { touches: [] });
  vi.useRealTimers();
  return lifted;
}

const details = () => document.querySelector('[aria-label="Listing details"]');

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("ListingsPanel keys", () => {
  it("moves to the next listing with j and shows its details with Enter", async () => {
    const user = userEvent.setup();
    const { frames } = await showListings();

    await user.keyboard("j");
    expect(frames[1]).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "BABYMETAL towel 2" })).toBeInTheDocument();
  });

  it("opens the listing with o, but leaves Ctrl and Cmd keys to the browser", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const user = userEvent.setup();
    await showListings();

    await user.keyboard("{Control>}o{/Control}{Meta>}o{/Meta}");
    expect(open).not.toHaveBeenCalled();
    await user.keyboard("o");
    expect(open).toHaveBeenCalledWith("https://jp.mercari.com/item/m1", "_blank", "noopener,noreferrer");
  });
});

describe("ListingsPanel on a phone", () => {
  it("shows a listing's details from a tap anywhere on it, so its title is not a link", async () => {
    const { frames } = await showListings({ phone: true });

    expect(within(frames[0]!).queryByRole("link")).toBeNull();
    fireEvent.click(within(frames[0]!).getByText("BABYMETAL towel 1"));
    expect(await screen.findByRole("heading", { name: "BABYMETAL towel 1" })).toBeInTheDocument();
  });

  it("shows a listing's actions after a long press, and not its details", async () => {
    const { frames } = await showListings({ phone: true });
    expect(screen.getByText("Press and hold a listing for more.")).toBeInTheDocument();

    const title = within(frames[0]!).getByText("BABYMETAL towel 1");
    // The lifted finger is not also a tap on the sheet that opened under it.
    expect(longPress(title)).toBe(false);
    fireEvent.click(title);
    const sheet = screen.getByRole("dialog", { name: "BABYMETAL towel 1" });
    expect(within(sheet).getByRole("link", { name: "Open on Mercari" })).toHaveAttribute("href", "https://jp.mercari.com/item/m1");
    expect(within(sheet).getByRole("button", { name: "Test with the draft" })).toBeInTheDocument();
    // No 🔔 without notifications, and no copying without a clipboard.
    expect(within(sheet).queryByRole("button", { name: /Follow/ })).toBeNull();
    expect(within(sheet).queryByRole("button", { name: "Copy the listing link" })).toBeNull();
    expect(details()).toBeNull();
    // The hint has done its job once the long press was used.
    expect(screen.queryByText("Press and hold a listing for more.")).toBeNull();

    fireEvent.click(within(sheet).getByRole("button", { name: "Show details" }));
    expect(await screen.findByRole("heading", { name: "BABYMETAL towel 1" })).toBeInTheDocument();
    expect(details()).not.toBeNull();
  });

  it("copies the listing link and follows the listing from the long-press sheet", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { frames, fetch, notify } = await showListings({ phone: true, session: MEMBER });

    longPress(within(frames[0]!).getByText("BABYMETAL towel 1"));
    fireEvent.click(screen.getByRole("button", { name: "Copy the listing link" }));
    expect(writeText).toHaveBeenCalledWith("https://jp.mercari.com/item/m1");
    await waitFor(() => expect(notify).toHaveBeenCalledWith("Copied the link."));

    longPress(within(frames[1]!).getByText("BABYMETAL towel 2"));
    fireEvent.click(screen.getByRole("button", { name: "Follow with 🔔 (DM me when it changes)" }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith("You get a DM when this listing changes.", "success"));
    expect(fetch).toHaveBeenCalledWith("/api/me/notifications/42", expect.objectContaining({ method: "PUT" }));
  });

  it("shows why the bot decided in a sheet, without opening the details", async () => {
    const { frames } = await showListings({ phone: true });

    fireEvent.click(within(frames[0]!).getByRole("button", { name: "Allowed. Show why." }));
    expect(screen.getByRole("dialog", { name: "Why it is allowed" })).toBeInTheDocument();
    expect(details()).toBeNull();
  });
});


const SEARCHES: AlertSummary[] = [
  { ...alertSummary("5", "20", "BABYMETAL towel", "9"), channel_name: "posters" },
  { ...alertSummary("6", "21", "Toy towel", "9"), channel_name: null },
];

/** A server's listings: the same towel saved by two searches in two channels, and once by a search since unregistered. */
function showServer({ filters = DEFAULT_LISTING_FILTERS, guildId = "9", owner = null, onTestTitle = vi.fn() }: {
  filters?: ListingFilters; guildId?: string; owner?: string | null; onTestTitle?: () => void } = {}) {
  const same = listing("1");
  const page: CandidatePage = { ...PAGE, total: 3, items: [
    same,
    { ...same, id: "2", alert_id: "6", channel_id: "21", channel_name: null, search_query: "Toy towel",
      decision: { ...same.decision, verdict: "filtered" }, verdict: "filtered" },
    { ...same, id: "3", alert_id: null, channel_id: "22", channel_name: "vinyl", search_query: "Old towel" },
  ] };
  const fetch = vi.fn((url: string) => Promise.resolve(Response.json(url === "/api/session" ? MEMBER : page)));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SearchReadOwner.Provider value={owner}>
        <ListingsPanel alertId={null} guildId={guildId} filters={filters} onFilters={() => undefined} onTestTitle={onTestTitle}
          searches={SEARCHES} />
      </SearchReadOwner.Provider>
    </QueryClientProvider>,
  );
  return { fetch, onTestTitle };
}

function asked(fetch: { mock: { calls: [string][] } }) {
  const call = fetch.mock.calls.find(([url]) => url.startsWith("/api/candidates?"));
  expect(call).toBeDefined();
  return new URL(call![0], "http://filter.lab").searchParams;
}

describe("ListingsPanel across a server", () => {
  it("names each listing's search and channel, and tests a title in the search that saved it", async () => {
    const user = userEvent.setup();
    const { fetch, onTestTitle } = showServer();
    const frames = await screen.findAllByRole("listitem");

    expect(frames.map((frame) => frame.textContent)).toEqual([
      expect.stringContaining("Search: BABYMETAL towel#posters"),
      expect.stringContaining("Search: Toy towelChannel …21"),
      expect.stringContaining("Search: Old towelUnregistered search · #vinyl"),
    ]);
    expect(asked(fetch).get("guild_id")).toBe("9");
    expect(asked(fetch).has("alert_id")).toBe(false);

    act(() => frames[1]!.focus());
    await user.keyboard("t");
    expect(onTestTitle).toHaveBeenLastCalledWith(expect.objectContaining({ alertId: "6" }));
    act(() => frames[2]!.focus());
    await user.keyboard("t");
    expect(onTestTitle).toHaveBeenLastCalledWith(expect.objectContaining({ alertId: null }));
  });

  it("filters by the search and channel chosen in this server, and ignores those chosen in another", async () => {
    const chosen = { guildId: "9", alertId: "6", channelId: "21" };
    const here = showServer({ filters: { ...DEFAULT_LISTING_FILTERS, scope: chosen } });
    await screen.findAllByRole("listitem");
    expect([asked(here.fetch).get("alert_id"), asked(here.fetch).get("channel_id"), asked(here.fetch).get("guild_id")])
      .toEqual(["6", "21", "9"]);
    cleanup();

    const elsewhere = showServer({ filters: { ...DEFAULT_LISTING_FILTERS, scope: { ...chosen, guildId: "8" } } });
    await screen.findAllByRole("listitem");
    expect(asked(elsewhere.fetch).has("alert_id")).toBe(false);
    expect(asked(elsewhere.fetch).has("channel_id")).toBe(false);
  });

  it("marks a search read only from its own listings, not while browsing a server", async () => {
    localStorage.removeItem("dashboard:read:me:5");
    showServer({ owner: "me", filters: { ...DEFAULT_LISTING_FILTERS, scope: { guildId: "9", alertId: "5", channelId: "" } } });
    await screen.findAllByRole("listitem");
    expect(localStorage.getItem("dashboard:read:me:5")).toBeNull();
    cleanup();

    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json(PAGE))));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SearchReadOwner.Provider value="me">
          <ListingsPanel alertId="5" guildId={null} filters={DEFAULT_LISTING_FILTERS} onFilters={() => undefined} onTestTitle={() => undefined} />
        </SearchReadOwner.Provider>
      </QueryClientProvider>,
    );
    await screen.findAllByRole("listitem");
    await waitFor(() => expect(localStorage.getItem("dashboard:read:me:5")).toBe("2"));
    expect(screen.queryByText(/^Search: /)).toBeNull();
    localStorage.removeItem("dashboard:read:me:5");
  });
});
