import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Login } from "./Login";

function show(props: Partial<ComponentProps<typeof Login>> = {}) {
  const client = new QueryClient();
  const onRetry = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <Login method="discord" ended={null} unreachable={null} onRetry={onRetry} onSignedIn={vi.fn()} {...props} />
    </QueryClientProvider>,
  );
  return { onRetry };
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("Login with Discord", () => {
  it("links to Discord sign-in and comes back to the same search and tab", () => {
    window.history.replaceState(null, "", "/?alert=5&tab=rules");
    show();
    expect(screen.getByRole("link", { name: "Sign in with Discord" }))
      .toHaveAttribute("href", "/auth/discord?next=%2F%3Falert%3D5%26tab%3Drules");
    expect(screen.queryByLabelText("Access key")).not.toBeInTheDocument();
  });

  it.each([
    ["cancelled", "You cancelled on Discord"],
    ["state", "This sign-in expired"],
    ["not_member", "not in any server this bot is in"],
    ["discord_unavailable", "couldn't reach Discord"],
    ["rate_limited", "Too many sign-in attempts"],
    ["cookie", "didn't keep the dashboard's sign-in cookie"],
    ["something_new", "Signing in didn't work"],
  ])("explains why sign-in came back with %s, then clears it from the address", (reason, text) => {
    window.history.replaceState(null, "", `/?alert=5&signin=${reason}`);
    show();
    expect(screen.getByRole("alert")).toHaveTextContent(text);
    expect(window.location.search).toBe("?alert=5");
    expect(screen.getByRole("link", { name: "Sign in with Discord" }))
      .toHaveAttribute("href", "/auth/discord?next=%2F%3Falert%3D5");
  });

  it("says when access was lost on Discord", () => {
    show({ ended: "revoked" });
    expect(screen.getByRole("alert")).toHaveTextContent("You are no longer in a server this bot is in");
  });

  it("shows the bot's name and avatar", () => {
    show({ title: "PosterFinder Dashboard", bot: { id: "9", name: "PosterFinder", avatar_url: "https://cdn.example/bot.png" } });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("PosterFinder Dashboard");
    expect(document.querySelector('img[src="https://cdn.example/bot.png"]')).not.toBeNull();
  });

  it("says when the session ran out", () => {
    show({ ended: "ended" });
    expect(screen.getByText(/Your session ended/)).toBeInTheDocument();
  });
});

describe("Login without Discord", () => {
  it("asks for the access key", () => {
    show({ method: "access_key" });
    expect(screen.getByLabelText(/Access key/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in with Discord" })).not.toBeInTheDocument();
  });

  it("offers to try again when the dashboard can't be reached", async () => {
    const user = userEvent.setup();
    const { onRetry } = show({ method: undefined, unreachable: new Error("The dashboard can't be reached.") });
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });
});
