import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Source } from "../../api/types";
import { alertSummary } from "../../test/fixtures";
import { theme } from "../../theme";
import { MarketplacesDialog } from "./MarketplacesDialog";

const ALL: Source[] = ["yahooauction", "mercari", "surugaya", "rakuma"];

function show(enabled: Source[] = ALL) {
  const onClose = vi.fn();
  const fetch = vi.fn((url: string) => Promise.resolve(url.endsWith("/api/session")
    ? Response.json({ authenticated: true, enabled_sources: enabled })
    : Response.json({ sources: ["mercari"], turned_on: [], turned_off: ["yahooauction", "surugaya", "rakuma"] })));
  vi.stubGlobal("fetch", fetch);
  const alert = { ...alertSummary("7", "201", "vinyl"), sources: ALL };
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MarketplacesDialog alert={alert} onClose={onClose} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { fetch, onClose };
}

afterEach(() => vi.unstubAllGlobals());

describe("MarketplacesDialog", () => {
  it("keeps Save disabled until a marketplace changes, then sends exactly the selected set", async () => {
    const user = userEvent.setup();
    const { fetch, onClose } = show();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("switch", { name: "Yahoo Auctions" }));
    await user.click(screen.getByRole("switch", { name: "Surugaya" }));
    await user.click(screen.getByRole("switch", { name: "Rakuma" }));
    expect(save).toBeEnabled();
    await user.click(save);
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    const call = fetch.mock.calls.find(([url]) => url.endsWith("/api/alerts/7/sources")) as unknown as [string, RequestInit];
    expect(call[1].method).toBe("PUT");
    expect(JSON.parse(call[1].body as string)).toEqual({ sources: ["mercari"] });
  });

  it("lets a search choose a marketplace the whole bot has off, and warns when nothing it checks is searched", async () => {
    const user = userEvent.setup();
    const { fetch } = show(["yahooauction", "mercari"]);
    // The session answer arrives after the dialog opens.
    await vi.waitFor(() => expect(screen.getAllByText(/^Off for the whole bot/)).toHaveLength(2));
    expect(screen.queryByText(/posts nothing/)).toBeNull();
    await user.click(screen.getByRole("switch", { name: "Yahoo Auctions" }));
    await user.click(screen.getByRole("switch", { name: "Mercari" }));
    // Surugaya and Rakuma are still chosen, but the bot searches neither.
    expect(screen.getByText(/checks no marketplace the bot searches/)).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Rakuma" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith("/api/alerts/7/sources"))).toBe(true));
    const call = fetch.mock.calls.find(([url]) => url.endsWith("/api/alerts/7/sources")) as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ sources: ["surugaya"] });
  });

  it("says that no marketplace pauses the search, and saves exactly that", async () => {
    const user = userEvent.setup();
    const { fetch } = show();
    expect(screen.getByRole("dialog", { name: "Marketplaces to check for vinyl" })).toBeInTheDocument();
    expect(screen.queryByText(/this search is paused/)).toBeNull();
    for (const name of ["Yahoo Auctions", "Mercari", "Surugaya", "Rakuma"]) await user.click(screen.getByRole("switch", { name }));
    expect(screen.getByText(/this search is paused/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith("/api/alerts/7/sources"))).toBe(true));
    const call = fetch.mock.calls.find(([url]) => url.endsWith("/api/alerts/7/sources")) as unknown as [string, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ sources: [] });
  });
});
