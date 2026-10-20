import { afterEach, describe, expect, it } from "vitest";

import { placeUrl, usePlace, type Place } from "./hooks";
import { act, renderHook } from "@testing-library/react";

const BASE: Place = { guildId: null, channelId: null, alertId: null, me: false, view: "status", tab: "listings",
  channelTab: "searches", statusTab: "overview", searchFilter: null };

afterEach(() => window.history.replaceState(null, "", "/"));

describe("the page in the address", () => {
  it("keeps links short and fits what sign-in may return to", () => {
    expect(placeUrl({ ...BASE, guildId: "11" })).toBe("/?guild=11");
    expect(placeUrl({ ...BASE, guildId: "11", view: "searches" })).toBe("/?guild=11&view=searches");
    expect(placeUrl({ ...BASE, guildId: "11", channelId: "201", channelTab: "cleanup" })).toBe("/?guild=11&channel=201&tab=cleanup");
    expect(placeUrl({ ...BASE, guildId: "11", channelId: "201", alertId: "5", tab: "rules" })).toBe("/?guild=11&alert=5&tab=rules");
    expect(placeUrl({ ...BASE, guildId: "11", statusTab: "graphs" })).toBe("/?guild=11&tab=graphs");
    expect(placeUrl({ ...BASE, guildId: "11", view: "searches", statusTab: "graphs" })).toBe("/?guild=11&view=searches");
    expect(placeUrl({ ...BASE, guildId: "11", view: "searches", searchFilter: "errors" })).toBe("/?guild=11&view=searches&filter=errors");
    // A quick filter belongs to the server's Searches page only.
    expect(placeUrl({ ...BASE, guildId: "11", view: "listings", searchFilter: "errors" })).toBe("/?guild=11&view=listings");
    expect(placeUrl({ ...BASE, guildId: "11", channelId: "201", searchFilter: "failed" })).toBe("/?guild=11&channel=201");
    expect(placeUrl({ ...BASE, guildId: "11", me: true })).toBe("/?view=me");
    // dashboard.py only sends people back to "/" with letters, digits, =, & and _ in the query.
    for (const url of ["/?guild=11&channel=201&tab=cleanup", "/?guild=11&view=searches&filter=pending", "/?view=me"]) expect(url).toMatch(/^\/(\?[A-Za-z0-9=&_-]{1,200})?$/);
  });

  it("still opens links from before the dashboard", () => {
    window.history.replaceState(null, "", "/?alert=5&tab=rules");
    const { result } = renderHook(() => usePlace());
    expect(result.current[0]).toMatchObject({ alertId: "5", tab: "rules", channelId: null, me: false });
  });

  it("ignores values that are not IDs or known tabs", () => {
    window.history.replaceState(null, "", "/?guild=abc&channel=1&tab=nope&view=me");
    const { result } = renderHook(() => usePlace());
    expect(result.current[0]).toMatchObject({ guildId: null, channelId: "1", tab: "listings", channelTab: "searches", statusTab: "overview", me: true });
  });

  it("keeps the Searches quick filter through reload and back, and drops unknown ones", () => {
    window.history.replaceState(null, "", "/?guild=11&view=searches&filter=pending");
    const { result } = renderHook(() => usePlace());
    expect(result.current[0]).toMatchObject({ guildId: "11", view: "searches", searchFilter: "pending" });
    act(() => result.current[1]({ searchFilter: "failed" }));
    expect(window.location.search).toBe("?guild=11&view=searches&filter=failed");
    expect(result.current[0].searchFilter).toBe("failed");
    act(() => result.current[1]({ searchFilter: null }));
    expect(window.location.search).toBe("?guild=11&view=searches");
    window.history.replaceState(null, "", "/?guild=11&view=searches&filter=nope");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(result.current[0].searchFilter).toBeNull();
  });

  it("reads the status tab from the address", () => {
    window.history.replaceState(null, "", "/?guild=11&tab=graphs");
    const { result } = renderHook(() => usePlace());
    expect(result.current[0]).toMatchObject({ guildId: "11", view: "status", statusTab: "graphs" });
  });
});
