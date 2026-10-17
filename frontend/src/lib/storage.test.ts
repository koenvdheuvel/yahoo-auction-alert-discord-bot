import { afterEach, describe, expect, it } from "vitest";

import { moveOldKeys } from "./storage";

describe("moving old storage keys", () => {
  afterEach(() => localStorage.clear());

  it("moves drafts, their owner and the view to the dashboard keys", () => {
    localStorage.setItem("filter-lab:draft:5", '{"ruleset":{}}');
    localStorage.setItem("filter-lab:draft-owner", "111");
    localStorage.setItem("filter-lab:view", "list");
    localStorage.setItem("other", "kept");
    moveOldKeys();
    expect(Object.keys(localStorage).sort()).toEqual(["dashboard:draft-owner", "dashboard:draft:5", "dashboard:view", "other"]);
    expect(localStorage.getItem("dashboard:draft:5")).toBe('{"ruleset":{}}');
    expect(localStorage.getItem("dashboard:draft-owner")).toBe("111");
  });

  it("keeps a newer value that is already under the new key", () => {
    localStorage.setItem("dashboard:view", "grid");
    localStorage.setItem("filter-lab:view", "list");
    moveOldKeys();
    expect(localStorage.getItem("dashboard:view")).toBe("grid");
    expect(localStorage.getItem("filter-lab:view")).toBeNull();
  });
});
