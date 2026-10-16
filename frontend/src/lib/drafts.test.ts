import { describe, expect, it } from "vitest";

import { clearAllDrafts, clearDraft, countDrafts, saveDraft } from "./drafts";
import { defaultRuleset } from "./ruleset";

describe("stored drafts", () => {
  it("saves one draft per alert and clears them without touching other settings", () => {
    localStorage.setItem("filter-lab:view", "list");
    saveDraft("5", { ruleset: defaultRuleset(), baseVersionId: "12" });
    saveDraft("scratch", { ruleset: defaultRuleset(), baseVersionId: null });
    expect(countDrafts()).toBe(2);
    const stored = JSON.parse(localStorage.getItem("filter-lab:draft:5") ?? "null") as { baseVersionId: string; savedAt: string };
    expect(stored.baseVersionId).toBe("12");
    expect(Number.isNaN(Date.parse(stored.savedAt))).toBe(false);

    clearDraft("5");
    expect(countDrafts()).toBe(1);
    clearAllDrafts();
    expect(countDrafts()).toBe(0);
    expect(localStorage.getItem("filter-lab:view")).toBe("list");
  });
});
