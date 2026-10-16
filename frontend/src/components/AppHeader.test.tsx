import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Session } from "../api/types";
import { theme } from "../theme";
import { AppHeader } from "./AppHeader";

const SIGNED_IN: Session = {
  authenticated: true, method: "discord", expires_in: 3600, replay_limit: 500,
  user: { id: "1", name: "Alice", username: "alice", avatar_url: "https://cdn.discordapp.com/embed/avatars/0.png" },
  guilds: [{ id: "11", name: "Poster hunters", icon_url: null }],
};

function show(session: Session) {
  const client = new QueryClient();
  client.setQueryData(keys.session, session);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={client}>
        <AppHeader showMenu={false} onMenu={vi.fn()} onTestTitle={vi.fn()} onHelp={vi.fn()} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return client;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppHeader", () => {
  it("shows who is signed in and signs out from the account menu", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn(() => Promise.resolve(Response.json({ authenticated: false, method: "discord" })));
    vi.stubGlobal("fetch", fetch);
    const client = show(SIGNED_IN);
    const account = screen.getByRole("button", { name: "Alice: account" });
    expect(account).toHaveTextContent("Alice");
    expect(account.querySelector("img")).toHaveAttribute("src", SIGNED_IN.user!.avatar_url);
    await user.click(account);
    expect(screen.getByText("@alice on Discord")).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(fetch).toHaveBeenCalledWith("/api/session", expect.objectContaining({ method: "DELETE" }));
    await vi.waitFor(() => expect(client.getQueryData(keys.session)).toEqual({ authenticated: false, method: "discord" }));
  });

  it("names the access key when there is no Discord user", async () => {
    const user = userEvent.setup();
    show({ ...SIGNED_IN, method: "access_key", user: null, guilds: null });
    await user.click(screen.getByRole("button", { name: "Access key: account" }));
    expect(screen.getByText("Signed in with the access key")).toBeInTheDocument();
  });
});
