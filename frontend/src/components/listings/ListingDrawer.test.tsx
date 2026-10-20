import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Candidate } from "../../api/types";
import { ListingDrawer } from "./ListingDrawer";
import { drag, setPhone } from "../../test/screen";

const LISTING: Candidate = {
  id: "1", alert_id: "5", channel_id: "20", search_query: "BABYMETAL towel", source: "mercari", external_id: "m1",
  title: "BABYMETAL towel", normalized_title: "babymetal towel", payload: { url: "https://jp.mercari.com/item/m1", price: 1500 },
  decision: { verdict: "accepted", normalized_title: "babymetal towel", reasons: [] }, verdict: "accepted",
  ruleset_version_id: "4", observation_kind: "listing", origin: "live", incomplete: false,
  observed_at: "2026-10-16T00:00:00Z", last_seen_at: "2026-10-16T00:00:00Z",
};

function show(props: Partial<ComponentProps<typeof ListingDrawer>> = {}) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json({ authenticated: true }))));
  const handlers = { onPrevious: vi.fn(), onNext: vi.fn(), onClose: vi.fn(), onTestTitle: vi.fn() };
  const client = new QueryClient();
  const element = (next: Partial<ComponentProps<typeof ListingDrawer>>) => (
    <QueryClientProvider client={client}>
      <ListingDrawer candidate={LISTING} position="2 of 3" hasPrevious hasNext {...handlers} {...next} />
    </QueryClientProvider>
  );
  const { rerender } = render(element(props));
  return { ...handlers, rerender: (next: Partial<ComponentProps<typeof ListingDrawer>>) => rerender(element(next)) };
}

/** The part of the sheet that scrolls: the photo and the facts, under the buttons. */
const content = () => document.querySelector("[data-no-swipe]")!.children[1]!;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ListingDrawer on a phone", () => {
  it("moves to the next listing with a swipe to the left and back with a swipe to the right", () => {
    setPhone();
    vi.useFakeTimers();
    const { onNext, onPrevious } = show();
    const title = screen.getByRole("heading", { name: "BABYMETAL towel" });

    drag(title, [[300, 400], [260, 402], [190, 404], [120, 405]]);
    act(() => { vi.advanceTimersByTime(200); });
    expect(onNext).toHaveBeenCalledTimes(1);
    drag(title, [[100, 400], [140, 402], [210, 404], [280, 405]]);
    act(() => { vi.advanceTimersByTime(200); });
    expect(onPrevious).toHaveBeenCalledTimes(1);
    // A short move is not a swipe.
    drag(title, [[200, 400], [188, 400], [185, 400]]);
    act(() => { vi.advanceTimersByTime(200); });
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("moves at once with reduced motion, and shows the next listing in place", () => {
    setPhone({ reducedMotion: true });
    const { onNext } = show();

    drag(screen.getByRole("heading", { name: "BABYMETAL towel" }), [[300, 400], [260, 402], [190, 404], [120, 405]]);
    expect(onNext).toHaveBeenCalledTimes(1);
    expect((content().firstElementChild as HTMLElement).style.transform).toBe("");
  });

  it("does not swipe past the last listing", () => {
    setPhone();
    vi.useFakeTimers();
    const { onNext } = show({ hasNext: false });

    drag(screen.getByRole("heading", { name: "BABYMETAL towel" }), [[300, 400], [260, 402], [190, 404], [120, 405]]);
    act(() => { vi.advanceTimersByTime(200); });
    expect(onNext).not.toHaveBeenCalled();
  });

  it("closes with a drag down that starts at the top of the content", () => {
    setPhone();
    const { onClose } = show();
    const title = screen.getByRole("heading", { name: "BABYMETAL towel" });

    // Scrolled down, the same drag only scrolls the content back up.
    Object.defineProperty(content(), "scrollTop", { value: 120, configurable: true, writable: true });
    drag(title, [[200, 300], [202, 340], [204, 420], [205, 480]]);
    expect(onClose).not.toHaveBeenCalled();

    content().scrollTop = 0;
    drag(title, [[200, 300], [202, 340], [204, 420], [205, 480]]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps showing the listing while it slides away", () => {
    setPhone();
    const { rerender } = show();

    rerender({ candidate: null, position: "", hasPrevious: false, hasNext: false });
    expect(screen.getByRole("heading", { name: "BABYMETAL towel" })).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
  });
});

describe("ListingDrawer on a desktop", () => {
  it("moves with j and k", () => {
    const { onNext, onPrevious } = show();
    const paper = document.querySelector('[aria-label="Listing details"]')!;

    fireEvent.keyDown(paper, { key: "j" });
    fireEvent.keyDown(paper, { key: "k" });
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onPrevious).toHaveBeenCalledTimes(1);
  });
});
