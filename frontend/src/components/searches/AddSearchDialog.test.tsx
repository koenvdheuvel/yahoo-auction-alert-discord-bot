import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CHANNELS, alertSummary } from "../../test/fixtures";
import { theme } from "../../theme";
import { setPhone } from "../../test/screen";
import { AddSearchDialog, SEARCH_QUERY_MAX_LENGTH } from "./AddSearchDialog";

function show(channelId: string | null = "201") {
  const onCreated = vi.fn();
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient()}>
        <AddSearchDialog open channels={CHANNELS} channelId={channelId} onClose={vi.fn()} onCreated={onCreated} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { onCreated };
}

afterEach(() => vi.unstubAllGlobals());

describe("AddSearchDialog", () => {
  it("offers only channels where the bot can post and you may change things", async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByRole("combobox", { name: /Channel/ }));
    // Category names are headings in the list, not choices.
    const options = within(screen.getByRole("listbox")).getAllByRole("option")
      .filter((option) => !option.classList.contains("MuiListSubheader-root")).map((option) => option.textContent);
    expect(options).toEqual(["welcome", "posters-yahoo", "sold-out", "old-posters"]);
    expect(screen.getByText("2 channels left out: the bot cannot post there, or you lack Manage Channels.")).toBeInTheDocument();
  });

  it("registers the query in the picked channel and shows what the server refused", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json({ error: "conflict", message: "A search for vinyl already exists in #posters-yahoo." },
        { status: 409 }))
      .mockResolvedValueOnce(Response.json(alertSummary("9", "201", "vinyl"), { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    const { onCreated } = show();
    const query = screen.getByRole("textbox", { name: /Search query/ });
    expect(query).toHaveAttribute("maxLength", String(SEARCH_QUERY_MAX_LENGTH));
    await user.type(query, "vinyl");
    await user.click(screen.getByRole("button", { name: "Add search" }));
    expect(await screen.findByText("A search for vinyl already exists in #posters-yahoo.")).toBeInTheDocument();
    expect(JSON.parse((fetch.mock.calls[0] as [string, RequestInit])[1].body as string))
      .toEqual({ channel_id: "201", search_query: "vinyl" });
    await user.click(screen.getByRole("button", { name: "Add search" }));
    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: "9" })));
  });

  it("uses the phone's own picker on a phone, with categories as groups", () => {
    setPhone();
    show();
    const picker = screen.getByRole("combobox", { name: /Channel/ });
    expect(picker.tagName).toBe("SELECT");
    expect([...picker.querySelectorAll("optgroup")].map((group) => group.label)).toEqual(["Posters", "Archive"]);
    expect([...picker.querySelectorAll("option")].map((option) => option.textContent))
      .toEqual(["# welcome", "# posters-yahoo", "↳ sold-out", "# old-posters"]);
    expect(picker).toHaveValue("201");
  });
});
