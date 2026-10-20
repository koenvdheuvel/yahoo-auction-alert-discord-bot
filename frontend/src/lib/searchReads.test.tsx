import { act, renderHook } from "@testing-library/react";
import { useState, type PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SearchReadOwner, useSearchRead } from "./searchReads";

const owner = (id: string | null) => ({ children }: PropsWithChildren) => (
  <SearchReadOwner.Provider value={id}>{children}</SearchReadOwner.Provider>
);

afterEach(() => {
  vi.restoreAllMocks();
  // Like clearing site storage in another tab; also discards any in-memory fallback.
  act(() => { window.dispatchEvent(new StorageEvent("storage", { key: null })); });
});

describe("search read positions", () => {
  it("survives remounts without marking another user or search as read", () => {
    const first = renderHook(() => useSearchRead("5", "10"), { wrapper: owner("alice") });
    expect(first.result.current.unread).toBe(true);
    act(() => first.result.current.markRead("10"));
    first.unmount();

    const returning = renderHook(() => useSearchRead("5", "10"), { wrapper: owner("alice") });
    const otherUser = renderHook(() => useSearchRead("5", "10"), { wrapper: owner("erin") });
    const otherSearch = renderHook(() => useSearchRead("6", "10"), { wrapper: owner("alice") });
    const accessKey = renderHook(() => useSearchRead("5", "10"), { wrapper: owner("access_key") });
    expect(returning.result.current.unread).toBe(false);
    expect(otherUser.result.current.unread).toBe(true);
    expect(otherSearch.result.current.unread).toBe(true);
    expect(accessKey.result.current.unread).toBe(true);
  });

  it("compares IDs precisely and never rewinds when a stale page finishes later", () => {
    const { result, rerender } = renderHook(({ latest }) => useSearchRead("5", latest), {
      initialProps: { latest: "9" }, wrapper: owner("alice"),
    });
    act(() => result.current.markRead("9"));
    rerender({ latest: "10" });
    expect(result.current.unread).toBe(true);
    act(() => result.current.markRead("9007199254740992"));
    rerender({ latest: "9007199254740993" });
    expect(result.current.unread).toBe(true);
    act(() => result.current.markRead("9007199254740993"));
    act(() => result.current.markRead("10"));
    expect(result.current.unread).toBe(false);
    expect(localStorage.getItem("dashboard:read:alice:5")).toBe("9007199254740993");
  });

  it("picks up another tab's reads and switches users without carrying their position over", () => {
    let switchUser: (id: string) => void = () => undefined;
    function Wrapper({ children }: PropsWithChildren) {
      const [user, setUser] = useState("alice");
      switchUser = setUser;
      return <SearchReadOwner.Provider value={user}>{children}</SearchReadOwner.Provider>;
    }
    const { result } = renderHook(() => useSearchRead("5", "12"), { wrapper: Wrapper });
    act(() => {
      localStorage.setItem("dashboard:read:alice:5", "12");
      window.dispatchEvent(new StorageEvent("storage", { key: "dashboard:read:alice:5", newValue: "12" }));
    });
    expect(result.current.unread).toBe(false);
    act(() => switchUser("erin"));
    expect(result.current.unread).toBe(true);
    act(() => switchUser("alice"));
    expect(result.current.unread).toBe(false);
  });

  it("ignores corrupt storage and keeps a tab-local position when storage is blocked", () => {
    localStorage.setItem("dashboard:read:alice:5", "not an ID");
    const { result, rerender } = renderHook(({ latest }) => useSearchRead("5", latest), {
      initialProps: { latest: "12" }, wrapper: owner("alice"),
    });
    expect(result.current.unread).toBe(true);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    act(() => result.current.markRead("12"));
    expect(result.current.unread).toBe(false);
    rerender({ latest: "13" });
    expect(result.current.unread).toBe(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    act(() => result.current.markRead("13"));
    expect(result.current.unread).toBe(false);
  });

  it("does not write a read position before a user is signed in or for an empty search", () => {
    const signedOut = renderHook(() => useSearchRead("5", "10"), { wrapper: owner(null) });
    act(() => signedOut.result.current.markRead("10"));
    expect(localStorage.length).toBe(0);
    const empty = renderHook(() => useSearchRead("5", null), { wrapper: owner("alice") });
    expect(empty.result.current.unread).toBe(false);
  });
});
