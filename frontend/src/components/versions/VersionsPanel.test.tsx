import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RuleVersion, RulesResponse } from "../../api/types";
import { defaultRuleset } from "../../lib/ruleset";
import type { Draft } from "../../lib/useDraft";
import { alertSummary } from "../../test/fixtures";
import { setPhone } from "../../test/screen";
import { theme } from "../../theme";
import { VersionsPanel } from "./VersionsPanel";

const RULESET = defaultRuleset();
const OLD: RuleVersion = {
  id: "11", version: 1, search_query: "beatmania", restored_from_version_id: null, created_at: "2026-10-15T00:00:00Z",
  ruleset: { ...RULESET, groups: [{ id: "g1", label: "Sets", policy: "exclude", match: "any", normalize: true,
    terms: [{ method: "contains", value: "セット" }] }] },
};
const CURRENT: RuleVersion = { ...OLD, id: "12", version: 2, ruleset: RULESET, created_at: "2026-10-16T00:00:00Z" };
const RULES: RulesResponse = {
  alert: { id: "1", channel_id: "20", search_query: "beatmania" }, active_version: CURRENT, versions: [CURRENT, OLD],
  versions_total: 2, legacy_filters: [], default_ruleset: RULESET,
};
const DRAFT: Draft = {
  ready: true, ruleset: RULESET, serialized: JSON.stringify(RULESET), published: CURRENT, publishedRuleset: RULESET,
  baseVersionId: "12", edited: true, outdated: false, update: vi.fn(), discard: vi.fn(), rebase: vi.fn(),
};

function Versions({ canChange }: { canChange: boolean }) {
  const rules = useQuery({ queryKey: ["rules", "1"], queryFn: () => RULES, initialData: RULES });
  return <VersionsPanel alert={alertSummary("1", "20", "beatmania")} rules={rules} draft={DRAFT} onEditRules={vi.fn()}
    canChange={canChange} />;
}

function show(canChange = true) {
  // The latest post removal is not known; the panel shows no notice for it.
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json({ error: "not_found" }, { status: 404 }))));
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Versions canChange={canChange} />
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Versions on a phone", () => {
  it("shows or hides a version's rules with a tap on the version", async () => {
    setPhone();
    const user = userEvent.setup();
    show();
    const version = screen.getByRole("button", { name: /^Version 1/ });
    expect(version).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Sets")).not.toBeInTheDocument();

    await user.click(version);
    expect(version).toHaveAttribute("aria-expanded", "true");
    const rules = document.getElementById(version.getAttribute("aria-controls")!);
    expect(within(rules!).getByText("Sets")).toBeInTheDocument();
    // The actions moved to the ⋮ menu.
    expect(screen.queryByRole("button", { name: "Load into draft" })).not.toBeInTheDocument();
  });

  it("keeps a version's actions in a sheet, and says why Restore is off", async () => {
    setPhone();
    const user = userEvent.setup();
    show(false);
    await user.click(screen.getByRole("button", { name: "More actions for version 1" }));
    const sheet = await screen.findByRole("dialog", { name: "Version 1" });
    expect(within(sheet).getByRole("button", { name: "Restore" })).toHaveAttribute("aria-disabled", "true");
    expect(within(sheet).getByText(/You need Manage Channels/)).toBeInTheDocument();

    // The draft has unpublished changes, so loading a version asks first.
    await user.click(within(sheet).getByRole("button", { name: "Load into draft" }));
    expect(await screen.findByRole("dialog", { name: "Replace your draft?" })).toBeInTheDocument();
  });

  it("opens the actions with a long press, and the lifted finger is not a tap", () => {
    vi.useFakeTimers();
    setPhone();
    show();
    const version = screen.getByRole("button", { name: /^Version 1/ });
    fireEvent.touchStart(version, { touches: [{ clientX: 10, clientY: 10 }] });
    act(() => { vi.advanceTimersByTime(500); });
    expect(screen.getByRole("dialog", { name: "Version 1" })).toBeInTheDocument();
    // fireEvent says false when the end of the touch was cancelled, which keeps the browser from tapping the sheet.
    expect(fireEvent.touchEnd(version, { touches: [] })).toBe(false);
    expect(version).toHaveAttribute("aria-expanded", "false");
  });

  it("restores from the sheet", async () => {
    setPhone();
    const user = userEvent.setup();
    show();
    await user.click(screen.getByRole("button", { name: "More actions for version 1" }));
    await user.click(within(await screen.findByRole("dialog", { name: "Version 1" })).getByRole("button", { name: "Restore" }));
    expect(await screen.findByRole("dialog", { name: "Restore version 1?" })).toBeInTheDocument();
  });
});

describe("Versions on a larger screen", () => {
  it("keeps the buttons on each version", async () => {
    const user = userEvent.setup();
    show();
    expect(screen.getAllByRole("button", { name: "Load into draft" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Restore" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Remove filtered posts" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^More actions/ })).not.toBeInTheDocument();

    const [, older] = screen.getAllByRole("button", { name: "Show rules" });
    await user.click(older!);
    expect(screen.getByRole("button", { name: "Hide rules" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Sets")).toBeInTheDocument();
  });
});
