import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChannelPost } from "../../api/types";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import { PostsPanel } from "./PostsPanel";

const POST: ChannelPost = {
  message_id: "900", posted_at: new Date().toISOString(), alert_id: "1", item_id: "77",
  listing: { id: "x1", source: "yahooauction", title: "BABYMETAL poster", price: 5000, stock: 1, buyout_price: 0,
    image_url: "", url: "https://page.auctions.yahoo.co.jp/jp/auction/x1" },
  hidden: false, subscribers: 2, subscribed_by_me: false, queued: false,
};

function show() {
  const fetch = vi.fn((path: string) => Promise.resolve(path.startsWith("/api/channels/201/posts")
    ? Response.json({ posts: [POST], next_before: null, notifications: true })
    : Response.json({ subscribed: true, created: true })));
  vi.stubGlobal("fetch", fetch);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PostsPanel channelId="201" guildId="11" channelName="posters" canManage />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("PostsPanel on a phone", () => {
  it("opens a post's actions on a long press, like a message in Discord's app", async () => {
    setPhone();
    const fetch = show();
    const title = await screen.findByText("BABYMETAL poster");
    vi.useFakeTimers();
    fireEvent.touchStart(title, { touches: [{ clientX: 10, clientY: 10 }] });
    act(() => { vi.advanceTimersByTime(500); });
    fireEvent.touchEnd(title, { touches: [] });
    vi.useRealTimers();

    const sheet = screen.getByRole("dialog", { name: "BABYMETAL poster" });
    expect(within(sheet).getByRole("link", { name: "Open in Discord" })).toHaveAttribute("href", "https://discord.com/channels/11/201/900");
    expect(within(sheet).getByRole("link", { name: "Open the listing" })).toHaveAttribute("href", POST.listing.url);
    // What the 🔔 count means is written out, since a finger cannot hover over it.
    expect(within(sheet).getByText("2 people get DMs for this listing. Who they are is not shown.")).toBeInTheDocument();
    await userEvent.setup().click(within(sheet).getByRole("button", { name: "Follow with 🔔" }));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/me/notifications/77", expect.objectContaining({ method: "PUT" })));
  });

  it("offers the same actions from the button at the end of the row", async () => {
    setPhone();
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "More for BABYMETAL poster" }));
    await user.click(within(screen.getByRole("dialog", { name: "BABYMETAL poster" })).getByRole("button", { name: "Hide in #posters" }));
    expect(await screen.findByRole("dialog", { name: "Hide this listing here?" })).toBeInTheDocument();
  });
});

describe("PostsPanel on a larger screen", () => {
  it("keeps the dense row with its links", async () => {
    show();
    expect(await screen.findByRole("link", { name: "Open in Discord" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Listing" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More for BABYMETAL poster" })).not.toBeInTheDocument();
  });
});
