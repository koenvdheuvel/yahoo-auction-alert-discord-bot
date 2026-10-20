import { ThemeProvider } from "@mui/material/styles";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { alertSummary } from "../../test/fixtures";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import { SearchList } from "./SearchList";

const ALERTS = [
  { ...alertSummary("1", "201", "BABYMETAL poster"), channel_name: "posters-yahoo", review_count: 2 },
  { ...alertSummary("2", "204", "Staff only"), channel_name: "staff" },
];

function show() {
  const onOpen = vi.fn();
  const onOpenChannel = vi.fn();
  const onUnregister = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <SearchList alerts={ALERTS} showChannel canChange={(alert) => alert.id === "1"} onOpen={onOpen}
        onOpenChannel={onOpenChannel} onUnregister={onUnregister} />
    </ThemeProvider>,
  );
  return { onOpen, onOpenChannel, onUnregister };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("SearchList on a phone", () => {
  it("shows each search as a card that opens it, with Unregister where you may change it", async () => {
    setPhone();
    const user = userEvent.setup();
    const { onOpen, onUnregister } = show();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const card = screen.getByRole("button", { name: "BABYMETAL poster" });
    expect(card).toHaveAccessibleDescription(/#posters-yahoo · 3 listings · 2 need review/);
    await user.click(card);
    expect(onOpen).toHaveBeenCalledWith(ALERTS[0]);
    await user.click(screen.getByRole("button", { name: "Unregister BABYMETAL poster" }));
    expect(onUnregister).toHaveBeenCalledWith(ALERTS[0]);
    // Without Manage Channels there is no button, and the card says why instead of a tooltip.
    expect(screen.queryByRole("button", { name: "Unregister Staff only" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Staff only" }))
      .toHaveAccessibleDescription(/You need Manage Channels in its channel to unregister it/);
  });

  it("opens the search's actions on a long press, like a message in Discord's app", () => {
    setPhone();
    vi.useFakeTimers();
    const { onOpen, onOpenChannel } = show();
    const card = screen.getByRole("button", { name: "Staff only" });
    fireEvent.touchStart(card, { touches: [{ clientX: 10, clientY: 10 }] });
    act(() => { vi.advanceTimersByTime(500); });
    // Lifting the finger is cancelled, so the browser sends no click to the sheet that just opened under it.
    expect(fireEvent.touchEnd(card, { touches: [] })).toBe(false);
    fireEvent.click(card);
    expect(onOpen).not.toHaveBeenCalled();

    const sheet = screen.getByRole("dialog", { name: "Staff only" });
    expect(within(sheet).getByRole("button", { name: "Unregister" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(within(sheet).getByRole("button", { name: "Open #staff" }));
    expect(onOpenChannel).toHaveBeenCalledWith("204");
  });
});

describe("SearchList on a larger screen", () => {
  it("keeps the table", () => {
    show();
    expect(screen.getByRole("table", { name: "Searches" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unregister Staff only" })).toBeDisabled();
  });
});
