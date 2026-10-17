import { ThemeProvider } from "@mui/material/styles";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { GuildSummary } from "../../api/types";
import { theme } from "../../theme";
import { ServerRail } from "./ServerRail";

const GUILDS: GuildSummary[] = [
  { id: "11", name: "Poster hunters", icon_url: null, level: "manager", searches: 3, failing_searches: 0, failed_deliveries: 0 },
  { id: "22", name: "Record shop", icon_url: null, level: "manager", searches: 1, failing_searches: 1, failed_deliveries: 2 },
];

describe("ServerRail", () => {
  it("shows home and each server, marks the open one and flags problems", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onHome = vi.fn();
    render(
      <ThemeProvider theme={theme}>
        <ServerRail guilds={GUILDS} selectedId="11" home={false} homeLabel="Your notifications" bot={null}
          onHome={onHome} onSelect={onSelect} />
      </ThemeProvider>,
    );
    expect(screen.getByRole("button", { name: "Poster hunters" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Record shop" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("PH")).toBeInTheDocument();
    await user.hover(screen.getByRole("button", { name: "Record shop" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Record shop: 1 search failed the last check; 2 posts or DMs could not be sent");
    await user.click(screen.getByRole("button", { name: "Record shop" }));
    expect(onSelect).toHaveBeenCalledWith("22");
    await user.click(screen.getByRole("button", { name: "Your notifications" }));
    expect(onHome).toHaveBeenCalled();
  });
});
