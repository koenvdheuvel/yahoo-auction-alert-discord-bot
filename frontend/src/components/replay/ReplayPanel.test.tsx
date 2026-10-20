import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keys } from "../../api/hooks";
import type { Change, ReplayItem, Verdict } from "../../api/types";
import { defaultRuleset } from "../../lib/ruleset";
import type { Draft } from "../../lib/useDraft";
import { alertSummary } from "../../test/fixtures";
import { setPhone } from "../../test/screen";
import { theme } from "../../theme";
import type { StoredReplay } from "../views/SearchView";
import { ReplayPanel } from "./ReplayPanel";

// The published rules' decision and the draft's, for each kind of change.
const VERDICTS: Record<Change, [Verdict, Verdict]> = {
  newly_allowed: ["filtered", "accepted"],
  newly_blocked: ["accepted", "filtered"],
  changed: ["accepted", "review"],
  unchanged: ["accepted", "accepted"],
};

function item(id: number, change: Change): ReplayItem {
  const [active, draft] = VERDICTS[change];
  return {
    candidate: { id: String(id), source: "mercari", external_id: `m${id}`, title: `Poster ${id}`, normalized_title: `poster ${id}`,
      observation_kind: "listing", origin: "live", incomplete: false, observed_at: "2026-10-16T00:00:00Z", last_seen_at: null,
      price: 1000, url: `https://jp.mercari.com/item/m${id}`, image_url: null },
    original_decision: { verdict: active, normalized_title: "", reasons: [] },
    active_decision: { verdict: active, normalized_title: "", reasons: [{ code: "match", message: "Published reason" }] },
    draft_decision: { verdict: draft, normalized_title: "", reasons: [{ code: "match", message: `Draft reason ${id}` }] },
    change,
  };
}

// 1 newly allowed, 2 newly filtered, 3 other changes and 4 unchanged.
const CHANGES: Change[] = ["newly_allowed", "newly_blocked", "newly_blocked", "changed", "changed", "changed",
  "unchanged", "unchanged", "unchanged", "unchanged"];
const ITEMS = CHANGES.map((change, index) => item(index + 1, change));

const RULESET = defaultRuleset();
const DRAFT: Draft = {
  ready: true, ruleset: RULESET, serialized: JSON.stringify(RULESET), published: null, publishedRuleset: RULESET,
  baseVersionId: null, edited: true, outdated: false, update: vi.fn(), discard: vi.fn(), rebase: vi.fn(),
};
const STORED: StoredReplay = {
  alertId: "1", serialized: DRAFT.serialized, ranAt: "2026-10-16T00:00:00Z",
  result: {
    items: ITEMS, active_version_id: null,
    summary: { total: 10, accepted: 5, filtered: 2, review: 3, newly_allowed: 1, newly_blocked: 2, changed: 3, unchanged: 4,
      available: 10, recent: 10, truncated: false, budget_exceeded: false },
  },
};

function show() {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json({ error: "not_found" }, { status: 404 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(keys.session, { authenticated: true, method: "access_key", replay_limit: 500 });
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={client}>
        <ReplayPanel alert={alertSummary("1", "20", "beatmania")} draft={DRAFT} stored={STORED} onResult={vi.fn()}
          autoRun={false} onAutoRun={vi.fn()} onEditRules={vi.fn()} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

/** The listings in the results table, without its heading row. */
const tableRows = () => within(screen.getByRole("table", { name: "Replay results" })).getAllByRole("row").length - 1;
const pressed = () => screen.getAllByRole("button", { pressed: true }).map((button) => button.textContent);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Replay results", () => {
  it("lets the counters choose every view and nothing else does, each listing exactly what its number counts", async () => {
    const user = userEvent.setup();
    show();
    // One control picks the view: the six counters, which are the only buttons with a pressed state.
    expect(screen.getAllByRole("button").filter((button) => button.hasAttribute("aria-pressed"))).toHaveLength(6);
    // Every change at first.
    expect(tableRows()).toBe(6);
    expect(pressed()).toEqual(["6changed"]);

    const views: [RegExp, number][] = [
      [/^1 ?newly allowed$/, 1],
      [/^2 ?newly filtered$/, 2],
      [/^3 ?other changes/, 3],
      [/^4 ?unchanged$/, 4],
      [/^10 ?everything checked$/, 10],
      [/^6 ?changed$/, 6],
    ];
    for (const [name, count] of views) {
      const counter = screen.getByRole("button", { name });
      await user.click(counter);
      expect(tableRows()).toBe(count);
      expect(counter).toHaveAttribute("aria-pressed", "true");
      expect(pressed()).toHaveLength(1);
    }
  });

  it("shows each listing as a card with its three decisions on a phone", async () => {
    setPhone();
    const user = userEvent.setup();
    show();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const cards = within(screen.getByRole("list", { name: "Replay results" })).getAllByRole("listitem");
    expect(cards).toHaveLength(6);

    const first = within(cards[0]!);
    expect(first.getByRole("link", { name: "Poster 1" })).toHaveAttribute("href", "https://jp.mercari.com/item/m1");
    expect(first.getByRole("button", { name: /^Recorded .*: Filtered\. Show why\.$/ })).toBeInTheDocument();
    expect(first.getByRole("button", { name: "Published rules: Filtered. Show why." })).toBeInTheDocument();
    expect(first.getByText("Newly allowed, was filtered")).toBeInTheDocument();

    // The reasons are one tap away.
    await user.click(first.getByRole("button", { name: "Your draft: Allowed. Show why." }));
    expect(await screen.findByText("Draft reason 1")).toBeInTheDocument();
  });
});
