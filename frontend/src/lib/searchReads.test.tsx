import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SearchReadOwner, useReadPositions, useSearchRead } from "./searchReads";

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
    const first = renderHook(() => useSearchRead("5"), { wrapper: owner("alice") });
    expect(first.result.current.readThrough).toBeNull();
    act(() => first.result.current.markRead("10"));
    first.unmount();

    const returning = renderHook(() => useSearchRead("5"), { wrapper: owner("alice") });
    const otherUser = renderHook(() => useSearchRead("5"), { wrapper: owner("erin") });
    const otherSearch = renderHook(() => useSearchRead("6"), { wrapper: owner("alice") });
    const accessKey = renderHook(() => useSearchRead("5"), { wrapper: owner("access_key") });
    expect(returning.result.current.readThrough).toBe("10");
    expect(otherUser.result.current.readThrough).toBeNull();
    expect(otherSearch.result.current.readThrough).toBeNull();
    expect(accessKey.result.current.readThrough).toBeNull();
  });

  it("compares IDs precisely and never rewinds when a stale page finishes later", () => {
    const { result } = renderHook(() => useSearchRead("5"), { wrapper: owner("alice") });
    act(() => result.current.markRead("9"));
    act(() => result.current.markRead("9007199254740992"));
    expect(result.current.readThrough).toBe("9007199254740992");
    act(() => result.current.markRead("9007199254740993"));
    act(() => result.current.markRead("10"));
    act(() => result.current.markRead("9007199254740992"));
    expect(result.current.readThrough).toBe("9007199254740993");
    expect(localStorage.getItem("dashboard:read:alice:5")).toBe("9007199254740993");
  });

  it("picks up another tab's reads and switches users without carrying their position over", () => {
    let switchUser: (id: string) => void = () => undefined;
    function Wrapper({ children }: PropsWithChildren) {
      const [user, setUser] = useState("alice");
      switchUser = setUser;
      return <SearchReadOwner.Provider value={user}>{children}</SearchReadOwner.Provider>;
    }
    const { result } = renderHook(() => ({ one: useSearchRead("5"), list: useReadPositions(["5", "6"]) }), { wrapper: Wrapper });
    act(() => {
      localStorage.setItem("dashboard:read:alice:5", "12");
      window.dispatchEvent(new StorageEvent("storage", { key: "dashboard:read:alice:5", newValue: "12" }));
    });
    expect(result.current.one.readThrough).toBe("12");
    expect([...result.current.list]).toEqual([["5", "12"], ["6", null]]);
    act(() => switchUser("erin"));
    expect(result.current.one.readThrough).toBeNull();
    expect([...result.current.list]).toEqual([["5", null], ["6", null]]);
    act(() => switchUser("alice"));
    expect(result.current.one.readThrough).toBe("12");
    expect([...result.current.list]).toEqual([["5", "12"], ["6", null]]);
  });

  it("ignores corrupt storage and keeps a tab-local position when storage is blocked", () => {
    // The server only takes positive signed 64-bit IDs, so one past that would fail a whole count request.
    localStorage.setItem("dashboard:read:alice:5", "9223372036854775808");
    localStorage.setItem("dashboard:read:alice:6", "not an ID");
    localStorage.setItem("dashboard:read:alice:7", "9223372036854775807");
    const { result } = renderHook(() => ({ five: useSearchRead("5"), six: useSearchRead("6"), list: useReadPositions(["5", "6", "7"]) }),
      { wrapper: owner("alice") });
    expect([...result.current.list]).toEqual([["5", null], ["6", null], ["7", "9223372036854775807"]]);
    act(() => result.current.five.markRead("9223372036854775809"));
    expect(result.current.five.readThrough).toBeNull();
    expect(localStorage.getItem("dashboard:read:alice:5")).toBe("9223372036854775808");

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    act(() => result.current.six.markRead("12"));
    expect(result.current.six.readThrough).toBe("12");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    act(() => result.current.six.markRead("13"));
    expect(result.current.six.readThrough).toBe("13");
  });

  it("does not write a read position before a user is signed in", () => {
    const signedOut = renderHook(() => useSearchRead("5"), { wrapper: owner(null) });
    act(() => signedOut.result.current.markRead("10"));
    expect(signedOut.result.current.readThrough).toBeNull();
    expect(localStorage.length).toBe(0);
  });
});
