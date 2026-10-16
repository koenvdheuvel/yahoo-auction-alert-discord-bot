import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keys } from "../../api/hooks";
import type { GuildSummary, Session } from "../../api/types";
import { theme } from "../../theme";
import { NoticeContext } from "../common/notify";
import { Shell } from "./Shell";

const MEMBER: Session = {
  authenticated: true, method: "discord", title: "PosterFinder Dashboard", bot: null, bot_running: true,
  user: { id: "7", name: "Bob", username: "bob", avatar_url: "" },
  guilds: [{ id: "11", name: "Poster hunters", icon_url: null, level: "member" }],
  features: { notifications: true, discord_data: true },
};
const GUILDS: GuildSummary[] = [{ id: "11", name: "Poster hunters", icon_url: null, level: "member" }];
const ITEM = {
  item_id: "5", source: "yahooauction", external_id: "x1", title: "BABYMETAL poster", price: 5000, buyout_price: 0,
  stock: 1, image_url: null, url: null, end_time: null, muted: false, updated_at: null, last_seen_at: null,
  waiting_dms: 0, posts: [{ channel_id: "31", message_id: "900", guild_id: "11", search_query: "BABYMETAL", channel_name: "posters" }],
};

function show(path: string) {
  window.history.replaceState(null, "", path);
  const answers: Record<string, unknown> = {
    "/api/guilds": { guilds: GUILDS },
    "/api/alerts": { alerts: [], totals: { archived_count: 0, unassigned_count: 0, guilds: {} } },
    "/api/me/notifications": { items: [ITEM, { item_id: "6", redacted: true }] },
  };
  const fetch = vi.fn((path: string) => Promise.resolve(path in answers ? Response.json(answers[path])
    : Response.json({ error: "not_found", message: "Not found" }, { status: 404 })));
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(keys.session, MEMBER);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={client}>
        <NoticeContext.Provider value={vi.fn()}><Shell /></NoticeContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("Shell for someone who is only a member", () => {
  it("starts on their notifications and never asks for a server's channels", async () => {
    const fetch = show("/");
    expect(await screen.findByText("BABYMETAL poster", {}, { timeout: 10_000 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your notifications");
    // The one they follow in a channel they cannot see has no details, but can still be stopped.
    expect(screen.getByText(/A listing in a channel you can't see/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Following" })).toHaveLength(2);
    // The channel is not a link: members do not get channel pages.
    expect(screen.queryByRole("button", { name: "#posters" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.map(([path]) => path)).not.toContainEqual(expect.stringContaining("/channels"));
  });

  it("shows only their notifications in a server where they are a member", async () => {
    const user = userEvent.setup();
    show("/?guild=11&view=searches");
    expect(await screen.findByText("BABYMETAL poster", {}, { timeout: 10_000 })).toBeInTheDocument();
    // On a phone the server and channel lists open from the menu button.
    await user.click(screen.getByRole("button", { name: "Open the server and channel lists" }));
    expect(await screen.findByText(/You are a member here/)).toBeInTheDocument();
    expect(screen.queryByText("Searches")).not.toBeInTheDocument();
    // Only listings posted in this server are listed here; the hidden one is not.
    expect(screen.queryByText(/A listing in a channel you can't see/)).not.toBeInTheDocument();
  });
});
