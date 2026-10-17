import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Candidate, CandidatePage } from "../../api/types";
import { ListingsPanel } from "./ListingsPanel";

// jsdom does no layout, so it has no scrollIntoView.
Element.prototype.scrollIntoView = () => undefined;

function listing(id: string): Candidate {
  const title = `BABYMETAL towel ${id}`;
  return {
    id, alert_id: "5", channel_id: "20", search_query: "BABYMETAL towel", source: "mercari", external_id: `m${id}`,
    title, normalized_title: title.toLowerCase(), payload: { url: `https://jp.mercari.com/item/m${id}`, price: 1500 },
    decision: { verdict: "accepted", normalized_title: title.toLowerCase(), reasons: [] }, verdict: "accepted",
    ruleset_version_id: "4", observation_kind: "listing", origin: "live", incomplete: false,
    observed_at: "2026-10-16T00:00:00Z", last_seen_at: "2026-10-16T00:00:00Z",
  };
}

const PAGE: CandidatePage = {
  items: [listing("1"), listing("2")], total: 2, has_more: false, next_cursor: null,
  facets: { verdict: { accepted: 2, filtered: 0, review: 0 } },
};

/** Shows two listings with keyboard focus on the first. */
async function showListings() {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json(PAGE))));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ListingsPanel alertId="5" filters={{ search: "", source: "", verdict: "", latest: true }}
        onFilters={() => undefined} onTestTitle={() => undefined} />
    </QueryClientProvider>,
  );
  const frames = await screen.findAllByRole("listitem");
  act(() => frames[0]!.focus());
  return frames;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ListingsPanel keys", () => {
  it("moves to the next listing with j and shows its details with Enter", async () => {
    const user = userEvent.setup();
    const frames = await showListings();

    await user.keyboard("j");
    expect(frames[1]).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "BABYMETAL towel 2" })).toBeInTheDocument();
  });

  it("opens the listing with o, but leaves Ctrl and Cmd keys to the browser", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const user = userEvent.setup();
    await showListings();

    await user.keyboard("{Control>}o{/Control}{Meta>}o{/Meta}");
    expect(open).not.toHaveBeenCalled();
    await user.keyboard("o");
    expect(open).toHaveBeenCalledWith("https://jp.mercari.com/item/m1", "_blank", "noopener,noreferrer");
  });
});
