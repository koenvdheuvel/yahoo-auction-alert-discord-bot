import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StoredListing } from "../../api/types";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import { HiddenPanel } from "./HiddenPanel";

const ITEM: StoredListing = {
  item_id: "5", source: "mercari", external_id: "m1", title: "BABYMETAL poster", price: 5000, buyout_price: 0, stock: 1,
  image_url: null, url: "https://jp.mercari.com/item/m1", end_time: null, muted: false, updated_at: null, last_seen_at: null,
};

function show(canChange = true) {
  const fetch = vi.fn((path: string) => Promise.resolve(path === "/api/channels/201/hidden"
    ? Response.json({ items: [ITEM], total: 1 })
    : Response.json({ hidden: false })));
  vi.stubGlobal("fetch", fetch);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <HiddenPanel channelId="201" canChange={canChange} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("HiddenPanel on a phone", () => {
  it("shows a hidden listing again from its row or from its sheet", async () => {
    setPhone();
    const user = userEvent.setup();
    const fetch = show();
    expect(await screen.findByRole("button", { name: "Show again" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Listing" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More for BABYMETAL poster" }));
    const sheet = screen.getByRole("dialog", { name: "BABYMETAL poster" });
    expect(within(sheet).getByRole("link", { name: "Open the listing" })).toHaveAttribute("href", ITEM.url);
    await user.click(within(sheet).getByRole("button", { name: "Show again" }));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/channels/201/hidden/5", expect.objectContaining({ method: "DELETE" })));
  });

  it("says why Show again is off without Manage Channels", async () => {
    setPhone();
    const user = userEvent.setup();
    show(false);
    expect(await screen.findByRole("button", { name: "Show again" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "More for BABYMETAL poster" }));
    expect(within(screen.getByRole("dialog")).getByText("You need Manage Channels here to show it again.")).toBeInTheDocument();
  });
});
