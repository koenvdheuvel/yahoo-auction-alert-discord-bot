import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RemovablePost, RemovalPreview } from "../../api/types";
import { usePostRemoval } from "../../lib/usePostRemoval";
import { PostRemovalPreview } from "./PostRemovalPreview";

const EXTRAS = "excluded_group_match:extras";
const SUBJECT = "required_group_missing:subject";

function post(messageId: string, reason: string): RemovablePost {
  return { message_id: messageId, posted_at: new Date().toISOString(), title: `BABYMETAL towel ${messageId}`, source: "mercari",
    external_id: `m${messageId}`, price: 1500, image_url: null, url: "https://jp.mercari.com/item/m1", reason };
}

const PREVIEW: RemovalPreview = {
  days: 30, posts_in_range: 9, checked: 9, partial: false, removable_total: 3, limit: 1000,
  posts: [post("1290000000000000001", EXTRAS), post("1290000000000000002", EXTRAS), post("1290000000000000003", SUBJECT)],
  reasons: [
    { key: EXTRAS, message: 'Excluded group "Extras" matched.', count: 2 },
    { key: SUBJECT, message: 'Required group "Subject" did not match.', count: 1 },
  ],
  kept: { allowed: 5, review: 0, subscribed: 1, incomplete: 0, unchecked: 0, queued: 0 },
  channel_id: "20", guild_id: "10", active_version_id: "4", bot_running: false,
};

function Harness() {
  const removal = usePostRemoval("5", undefined, true);
  return (
    <>
      <PostRemovalPreview removal={removal} />
      <output aria-label="Chosen posts">{removal.selected.join(",")}</output>
    </>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PostRemovalPreview", () => {
  it("shows what goes and why, and keeps the posts of an unticked reason", async () => {
    // The client always sends a JSON string body.
    const fetch = vi.fn((_url: string, _init: RequestInit & { body: string }) => Promise.resolve(Response.json(PREVIEW)));
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><Harness /></QueryClientProvider>);

    expect(await screen.findByText("3 posts will be removed from Discord.")).toBeInTheDocument();
    expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({ days: 30 });
    expect(screen.getByText("Kept: 1 post has 🔔 subscribers.")).toBeInTheDocument();
    expect(screen.getByText(/posts are removed when it runs next/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Discord" })[0]).toHaveAttribute(
      "href", "https://discord.com/channels/10/20/1290000000000000001");

    await user.click(screen.getByRole("checkbox", { name: /Required group "Subject" did not match/ }));
    expect(screen.getByText("2 posts will be removed from Discord.")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Chosen posts" })).toHaveTextContent("1290000000000000001,1290000000000000002");

    await user.click(screen.getByRole("combobox", { name: "Posts from" }));
    await user.click(screen.getByRole("option", { name: "All time" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetch.mock.calls[1]![1].body)).toEqual({ days: null });
  });
});
