import { describe, expect, it } from "vitest";

import type { RemovablePost } from "../api/types";
import { discordLink, reasonLabel, selectedPosts } from "./removal";

function post(messageId: string, reason: string): RemovablePost {
  return { message_id: messageId, posted_at: "2026-10-16T09:00:00Z", title: "BABYMETAL poster", source: "mercari",
    external_id: "m1", price: 3000, image_url: null, url: null, reason };
}

describe("selectedPosts", () => {
  it("leaves out the posts of the reasons the operator keeps", () => {
    const posts = [post("1", "excluded"), post("2", "missing"), post("3", "excluded")];
    expect(selectedPosts(posts, new Set())).toEqual(["1", "2", "3"]);
    expect(selectedPosts(posts, new Set(["excluded"]))).toEqual(["2"]);
  });
});

describe("discordLink", () => {
  it("needs the server ID", () => {
    expect(discordLink("10", "20", "30")).toBe("https://discord.com/channels/10/20/30");
    expect(discordLink(null, "20", "30")).toBeNull();
  });
});

describe("reasonLabel", () => {
  it("drops the full stop", () => {
    expect(reasonLabel('Excluded group "Extras" matched.')).toBe('Excluded group "Extras" matched');
  });
});
