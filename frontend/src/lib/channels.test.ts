import { describe, expect, it } from "vitest";

import { CHANNELS } from "../test/fixtures";
import { allChannels, channelLabel, findChannel, postableChannels, postingProblem } from "./channels";

describe("channel lists", () => {
  it("walks channels and their threads in the sidebar's order", () => {
    expect(allChannels(CHANNELS).map((channel) => channel.name))
      .toEqual(["welcome", "posters-yahoo", "sold-out", "quiet", "staff", "old-posters"]);
    expect(findChannel(CHANNELS, "203")?.kind).toBe("thread");
    expect(findChannel(CHANNELS, "404")).toBeNull();
  });

  it("offers new searches only where the bot can post and you may change the channel", () => {
    expect(postableChannels(CHANNELS).map((channel) => channel.name))
      .toEqual(["welcome", "posters-yahoo", "sold-out", "old-posters"]);
  });

  it("says why the bot cannot post", () => {
    expect(postingProblem(findChannel(CHANNELS, "202")!)).toBe("The bot needs Add Reactions here.");
    expect(postingProblem(findChannel(CHANNELS, "201")!)).toBeNull();
    expect(channelLabel("999000000000000123", null)).toBe("Channel …000123");
  });
});
