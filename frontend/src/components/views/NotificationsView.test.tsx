import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Subscription } from "../../api/types";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import { NotificationsView } from "./NotificationsView";

const ITEM: Subscription = {
  item_id: "5", source: "yahooauction", external_id: "x1", title: "BABYMETAL poster", price: 5000, buyout_price: 0,
  stock: 1, image_url: null, url: "https://page.auctions.yahoo.co.jp/jp/auction/x1", end_time: null, muted: false,
  updated_at: null, last_seen_at: null, waiting_dms: 0,
  posts: [{ channel_id: "31", message_id: "900", guild_id: "11", search_query: "BABYMETAL", channel_name: "posters" }],
};

function show() {
  const fetch = vi.fn((path: string) => Promise.resolve(path === "/api/me/notifications"
    ? Response.json({ items: [ITEM, { item_id: "6", redacted: true }] })
    : Response.json({ subscribed: false })));
  vi.stubGlobal("fetch", fetch);
  const onOpenChannel = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <NotificationsView guildId={null} followHere={false} onOpenChannel={onOpenChannel} canOpen={() => false} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("NotificationsView on a phone", () => {
  it("keeps Unfollow on each card and moves the small links into a sheet", async () => {
    setPhone();
    const user = userEvent.setup();
    const fetch = show();
    expect(await screen.findByText("BABYMETAL poster")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Following" })).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "post" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More for BABYMETAL poster" }));
    const sheet = screen.getByRole("dialog", { name: "BABYMETAL poster" });
    expect(within(sheet).getByRole("link", { name: "Open in Discord (#posters)" }))
      .toHaveAttribute("href", "https://discord.com/channels/11/31/900");
    expect(within(sheet).getByRole("link", { name: "Open the listing" })).toHaveAttribute("href", ITEM.url);
    // Members do not get channel pages.
    expect(within(sheet).queryByRole("button", { name: /in the dashboard/ })).not.toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Stop following" }));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/me/notifications/5", expect.objectContaining({ method: "DELETE" })));
  });
});
