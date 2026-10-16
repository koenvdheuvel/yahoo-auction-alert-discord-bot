import type { UseQueryResult } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { AlertSummary, AlertsResponse, Guild } from "../api/types";
import { AlertNav } from "./AlertNav";

const GUILDS: Guild[] = [
  { id: "11", name: "Poster hunters", icon_url: null },
  { id: "22", name: "Record shop", icon_url: null },
];

function alert(id: string, guildId: string, query: string): AlertSummary {
  return { id, guild_id: guildId, channel_id: `9${guildId}`, channel_name: `channel-${guildId}`, search_query: query,
    archived_count: 1, listing_count: 1, accepted_count: 1, filtered_count: 0, review_count: 0, labeled_count: 0,
    last_seen_at: null, active_version_id: null };
}

const data: AlertsResponse = {
  alerts: [alert("1", "11", "BABYMETAL poster"), alert("2", "22", "Vinyl")],
  totals: { archived_count: 2, unassigned_count: 0, guilds: {} },
};

function show(props: Partial<ComponentProps<typeof AlertNav>> = {}) {
  const onGuild = vi.fn();
  const alerts = { data, isPending: false, isError: false, isSuccess: true } as UseQueryResult<AlertsResponse>;
  render(<AlertNav alerts={alerts} selectedId={null} onSelect={vi.fn()} guilds={GUILDS} guildId="11" onGuild={onGuild}
    total={1} {...props} />);
  return { onGuild };
}

describe("AlertNav", () => {
  it("lists only the picked server's searches and switches servers", async () => {
    const user = userEvent.setup();
    const { onGuild } = show();
    expect(screen.getByText("BABYMETAL poster")).toBeInTheDocument();
    expect(screen.queryByText("Vinyl")).not.toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Server" }));
    await user.click(within(screen.getByRole("listbox")).getByText("Record shop"));
    expect(onGuild).toHaveBeenCalledWith("22");
  });

  it("names the one server without a picker", () => {
    show({ guilds: [GUILDS[0]!], guildId: null });
    expect(screen.queryByRole("combobox", { name: "Server" })).not.toBeInTheDocument();
    expect(screen.getByText("Poster hunters")).toBeInTheDocument();
  });

  it("shows every search with the access key", () => {
    show({ guilds: null, guildId: null });
    expect(screen.getByText("BABYMETAL poster")).toBeInTheDocument();
    expect(screen.getByText("Vinyl")).toBeInTheDocument();
  });
});
