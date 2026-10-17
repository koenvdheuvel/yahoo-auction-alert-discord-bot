import { describe, expect, it } from "vitest";

import { claimDrafts, clearAllDrafts, clearDraft, countDrafts, saveDraft } from "./drafts";
import { defaultRuleset } from "./ruleset";

describe("stored drafts", () => {
  it("saves one draft per alert and clears them without touching other settings", () => {
    localStorage.setItem("dashboard:view", "list");
    saveDraft("5", { ruleset: defaultRuleset(), baseVersionId: "12" });
    saveDraft("scratch", { ruleset: defaultRuleset(), baseVersionId: null });
    expect(countDrafts()).toBe(2);
    const stored = JSON.parse(localStorage.getItem("dashboard:draft:5") ?? "null") as { baseVersionId: string; savedAt: string };
    expect(stored.baseVersionId).toBe("12");
    expect(Number.isNaN(Date.parse(stored.savedAt))).toBe(false);

    clearDraft("5");
    expect(countDrafts()).toBe(1);
    clearAllDrafts();
    expect(countDrafts()).toBe(0);
    expect(localStorage.getItem("dashboard:view")).toBe("list");
  });

  it("keeps drafts for the same person and removes another person's", () => {
    saveDraft("5", { ruleset: defaultRuleset(), baseVersionId: null });
    // Drafts from before owners were recorded are kept.
    claimDrafts("111");
    expect(countDrafts()).toBe(1);
    claimDrafts("111");
    expect(countDrafts()).toBe(1);
    claimDrafts("222");
    expect(countDrafts()).toBe(0);
    saveDraft("5", { ruleset: defaultRuleset(), baseVersionId: null });
    claimDrafts("access_key");
    expect(countDrafts()).toBe(0);
  });
});
