import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useState } from "react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlertSummary } from "../api/types";
import { alertSummary } from "../test/fixtures";
import { SearchReadOwner, useSearchRead } from "./searchReads";
import { useSearchUnreadStates } from "./unreadCounts";

interface Call {
  readThrough: Record<string, string | null>;
  respond: (counts: Record<string, number>) => void;
  fail: () => void;
}

/** Answers nothing until a test says so, so each test decides what arrives when. */
function stubCounts(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn((_path: string, init: RequestInit) => new Promise<Response>((resolve) => {
    const body = JSON.parse(init.body as string) as { read_through: Record<string, string | null> };
    calls.push({ readThrough: body.read_through,
      respond: (counts) => resolve(Response.json({ counts })),
      fail: () => resolve(Response.json({ error: "busy", message: "Busy" }, { status: 500 })) });
  })));
  return calls;
}

const unread = (id: string, latest: string | null): AlertSummary => ({ ...alertSummary(id, "201", `search ${id}`), latest_candidate_id: latest });
const countOf = (count: number) => ({ kind: "count", count });

function app(user = "alice") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}><SearchReadOwner.Provider value={user}>{children}</SearchReadOwner.Provider></QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => { window.dispatchEvent(new StorageEvent("storage", { key: null })); });
});

describe("unread counts of the listed searches", () => {
  it("claims no number while counting, for a zero, or for a search the server left out", async () => {
    const calls = stubCounts();
    const alerts = [unread("5", "12"), unread("6", "20"), unread("7", "30")];
    const { result } = renderHook(() => useSearchUnreadStates(alerts), { wrapper: app() });
    expect(result.current.get("5")).toEqual({ kind: "loading" });

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.readThrough).toEqual({ "5": null, "6": null, "7": null });
    calls[0]!.respond({ "5": 3, "6": 0 });
    await waitFor(() => expect(result.current.get("5")).toEqual(countOf(3)));
    expect(result.current.has("6")).toBe(false);
    expect(result.current.has("7")).toBe(false);
  });

  it("says the count is unavailable, never none, when asking fails", async () => {
    const calls = stubCounts();
    const alerts = [unread("5", "12")];
    const { result } = renderHook(() => useSearchUnreadStates(alerts), { wrapper: app() });
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0]!.fail();
    await waitFor(() => expect(result.current.get("5")).toEqual({ kind: "unavailable" }));
  });

  it("does not reuse a count after its read cursor advances", async () => {
    const calls = stubCounts();
    const alerts = [unread("5", "12")];
    const { result } = renderHook(() => ({ states: useSearchUnreadStates(alerts), read: useSearchRead("5") }), { wrapper: app() });
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0]!.respond({ "5": 9 });
    await waitFor(() => expect(result.current.states.get("5")).toEqual(countOf(9)));

    act(() => result.current.read.markRead("10"));
    expect(result.current.states.get("5")).toEqual({ kind: "loading" });
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1]!.respond({ "5": 2 });
    await waitFor(() => expect(result.current.states.get("5")).toEqual(countOf(2)));

    act(() => result.current.read.markRead("12"));
    expect(result.current.states.has("5")).toBe(false);
  });

  it("keeps the last count of a search while a newer listing is counted", async () => {
    const calls = stubCounts();
    const { result, rerender } = renderHook(({ alerts }) => useSearchUnreadStates(alerts), {
      initialProps: { alerts: [unread("5", "12"), unread("6", "20")] }, wrapper: app(),
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0]!.respond({ "5": 3, "6": 1 });
    await waitFor(() => expect(result.current.get("5")).toEqual(countOf(3)));

    rerender({ alerts: [unread("5", "13"), unread("6", "20")] });
    expect(result.current.get("5")).toEqual(countOf(3));
    expect(result.current.get("6")).toEqual(countOf(1));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1]!.respond({ "5": 4, "6": 1 });
    await waitFor(() => expect(result.current.get("5")).toEqual(countOf(4)));
  });

  it("never shows one person's count to another, who is asked about their own cursors", async () => {
    localStorage.setItem("dashboard:read:alice:5", "10");
    const calls = stubCounts();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let switchUser: (id: string) => void = () => undefined;
    function Wrapper({ children }: PropsWithChildren) {
      const [user, setUser] = useState("alice");
      switchUser = setUser;
      return <QueryClientProvider client={client}><SearchReadOwner.Provider value={user}>{children}</SearchReadOwner.Provider></QueryClientProvider>;
    }
    const alerts = [unread("5", "12")];
    const { result } = renderHook(() => useSearchUnreadStates(alerts), { wrapper: Wrapper });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.readThrough).toEqual({ "5": "10" });
    calls[0]!.respond({ "5": 2 });
    await waitFor(() => expect(result.current.get("5")).toEqual(countOf(2)));

    act(() => switchUser("erin"));
    expect(result.current.get("5")).toEqual({ kind: "loading" });
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]!.readThrough).toEqual({ "5": null });
    calls[1]!.respond({ "5": 7 });
    await waitFor(() => expect(result.current.get("5")).toEqual(countOf(7)));
  });
});
