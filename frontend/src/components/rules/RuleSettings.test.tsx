import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DiscordFilter } from "../../api/types";
import { defaultRuleset } from "../../lib/ruleset";
import { RuleSettings } from "./RuleSettings";
import { setScreen } from "../../test/screen";

const FILTERS: DiscordFilter[] = [{ id: 12, method: "text", policy: "blacklist", value: "缶バッジ", enabled: true, matches: 31 }];
const NOTE = "You need Manage Channels in this search's channel to delete filters.";

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RuleSettings ruleset={defaultRuleset()} onChange={() => undefined} filters={FILTERS} alertId="5" priceError={null} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RuleSettings", () => {
  it("says on touch screens why a Discord filter cannot be deleted, since tooltips do not open from a tap", () => {
    setScreen(390);
    show();
    expect(screen.getByRole("button", { name: "Delete filter 缶バッジ" })).toBeDisabled();
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it("leaves the reason to the tooltip with a mouse", () => {
    show();
    expect(screen.getByRole("button", { name: "Delete filter 缶バッジ" })).toBeDisabled();
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });
});
