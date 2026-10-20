import { ThemeProvider } from "@mui/material/styles";
import type { UseQueryResult } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChannelList } from "../../api/types";
import type { Place } from "../../lib/hooks";
import { CHANNELS, alertSummary } from "../../test/fixtures";
import { theme } from "../../theme";
import { ChannelSidebar } from "./ChannelSidebar";
import { setPhone } from "../../test/screen";

const PLACE: Place = { guildId: "11", channelId: null, alertId: null, me: false, view: "status", tab: "listings",
  channelTab: "searches", statusTab: "overview" };
const ALERTS = [alertSummary("1", "201", "BABYMETAL poster"), alertSummary("2", "203", "Sold out"),
  alertSummary("3", "999000000000000123", "Gone"), alertSummary("4", "777", "Elsewhere", "22")];

function show(props: Partial<ComponentProps<typeof ChannelSidebar>> = {}) {
  const onNavigate = vi.fn();
  const channels = { data: CHANNELS, isPending: false, isError: false, isSuccess: true } as UseQueryResult<ChannelList>;
  render(
    <ThemeProvider theme={theme}>
      <ChannelSidebar guildName="Poster hunters" channels={channels} alerts={ALERTS} guildId="11" place={PLACE}
        onNavigate={onNavigate} home={null} footer={null} {...props} />
    </ThemeProvider>,
  );
  return { onNavigate };
}

afterEach(() => vi.unstubAllGlobals());

const rowNames = (container: HTMLElement) =>
  within(container).getAllByRole("button").map((button) => button.textContent?.replace(/\d+$/, "").trim());

describe("ChannelSidebar", () => {
  it("lists categories and channels in Discord's order, with each channel's searches under it", () => {
    show();
    const nav = screen.getByRole("navigation", { name: "Channels" });
    expect(rowNames(nav)).toEqual([
      "Status", "Searches", "All listings",
      "welcome",
      "Posters", "posters-yahoo", "BABYMETAL poster", "sold-out", "Sold out", "quiet", "staff",
      "Archive", "old-posters",
      "…000123deleted", "Gone",
    ]);
    // Searches of another server are not in this one's list.
    expect(screen.queryByText("Elsewhere")).not.toBeInTheDocument();
  });

  it("flags a channel where the bot cannot post", () => {
    show();
    expect(screen.getByLabelText("The bot needs Add Reactions here.")).toBeInTheDocument();
  });

  it("opens channels and searches, and folds a category away", async () => {
    const user = userEvent.setup();
    const { onNavigate } = show();
    await user.click(screen.getByRole("button", { name: /posters-yahoo/ }));
    expect(onNavigate).toHaveBeenCalledWith({ channelId: "201", alertId: null, me: false });
    await user.click(screen.getByRole("button", { name: /BABYMETAL poster/ }));
    expect(onNavigate).toHaveBeenCalledWith({ alertId: "1", channelId: null, me: false });
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(screen.queryByText("old-posters")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("dashboard:collapsed")!)).toEqual(["300"]);
  });

  it("says when Discord did not answer and lists the channels by ID", () => {
    const fallback: ChannelList = { ...CHANNELS, source: "none", discord_unavailable: true, sections: [],
      unknown: [{ id: "201", deleted: false, searches: 1, hidden: 0 }] };
    show({ channels: { data: fallback, isPending: false, isError: false, isSuccess: true } as UseQueryResult<ChannelList> });
    expect(screen.getByText("Discord did not answer, so channels are shown by ID.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /…201unknown/ })).toBeInTheDocument();
  });

  it("writes out on touch screens what a mouse sees on hover", () => {
    setPhone();
    show();
    expect(screen.getByRole("button", { name: /^quiet/ })).toHaveTextContent("quietThe bot needs Add Reactions here.");
  });

  it("marks home's one page as open, also before the address names it", () => {
    show({ home: { label: "Home", notifications: true } });
    expect(screen.getByRole("button", { name: "Your notifications" })).toHaveAttribute("aria-current", "page");
  });
});
