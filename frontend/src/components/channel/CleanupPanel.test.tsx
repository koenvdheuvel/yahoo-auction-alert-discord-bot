import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { theme } from "../../theme";
import { NoticeContext } from "../common/notify";
import { CleanupPanel } from "./CleanupPanel";

afterEach(() => vi.unstubAllGlobals());

it("never starts a history deletion before confirmation, and cancelling leaves the channel untouched", async () => {
  const user = userEvent.setup();
  const fetch = vi.fn((path: string, _options?: RequestInit) => {
    if (path.endsWith("/removal-preview")) {
      return Promise.resolve(Response.json({ posts: [], posts_in_range: 1, removable_total: 0, limit: 100,
        kept: { subscribed: 1, queued: 0 }, bot_running: true }));
    }
    if (path.endsWith("/history-scan")) return Promise.resolve(Response.json({ available: true, scan: null }));
    return Promise.resolve(Response.json({ run: null, bot_running: true }));
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <NoticeContext.Provider value={vi.fn()}>
          <CleanupPanel channelId="201" channelName="posters" searches={[]} canManage posting={null} />
        </NoticeContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  await user.click(screen.getByRole("button", { name: "Advanced: delete recent bot posts" }));
  const start = await screen.findByRole("button", { name: "Delete the latest bot posts" });
  await waitFor(() => expect(start).toBeEnabled());
  await user.click(start);
  const confirmation = screen.getByRole("dialog");
  expect(within(confirmation).getByRole("alert")).toHaveTextContent(/no preview, follower protection, or undo/i);
  expect(fetch.mock.calls.filter(([path, options]) => path.endsWith("/history-scan") && options?.method === "POST")).toHaveLength(0);
  await user.click(within(confirmation).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(fetch.mock.calls.filter(([path, options]) => path.endsWith("/history-scan") && options?.method === "POST")).toHaveLength(0);

  const count = screen.getByRole("textbox", { name: "Maximum posts to delete" });
  await user.clear(count);
  await user.type(count, "4");
  await user.click(start);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete bot posts" }));
  await waitFor(() => {
    const writes = fetch.mock.calls.filter(([path, options]) => path.endsWith("/history-scan") && options?.method === "POST");
    expect(writes).toHaveLength(1);
    expect(writes[0]![0]).toBe("/api/channels/201/history-scan");
    expect(JSON.parse(writes[0]![1]!.body as string)).toEqual({ action: "delete_bot_posts", count: 4 });
  });
});
