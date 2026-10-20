import { ThemeProvider } from "@mui/material/styles";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RuleVersion, Ruleset } from "../../api/types";
import { alertSummary } from "../../test/fixtures";
import type { Draft } from "../../lib/useDraft";
import { theme } from "../../theme";
import { DraftBar } from "./DraftBar";
import { setScreen, showKeyboard } from "../../test/screen";

const RULESET: Ruleset = {
  version: 1, normalization: { nfkc: true, casefold: true, collapse_whitespace: true, kana_fold: false }, include_legacy: true,
  groups: [], price: { min: null, max: null }, sources: [],
};
const PUBLISHED: RuleVersion = { id: "4", version: 4, search_query: "BABYMETAL", ruleset: RULESET, restored_from_version_id: null,
  created_at: "2026-10-16T00:00:00Z" };

function draft(changes: Partial<Draft> = {}): Draft {
  return { ready: true, ruleset: RULESET, serialized: "{}", published: PUBLISHED, publishedRuleset: RULESET, baseVersionId: "4",
    edited: true, outdated: false, update: vi.fn(), discard: vi.fn(), rebase: vi.fn(), ...changes };
}

function show(current: Draft, canChange = true) {
  const actions = { onPublish: vi.fn(), onTestTitle: vi.fn(), onReplay: vi.fn() };
  render(
    <ThemeProvider theme={theme}>
      <input aria-label="Group name" />
      <DraftBar draft={current} alert={alertSummary("5", "20", "BABYMETAL")} checking={false} checkFailed={null} invalid={null}
        replayedAt={null} canPublish={current.edited && !current.outdated} canChange={canChange} publishing={false} {...actions} />
    </ThemeProvider>,
  );
  return actions;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DraftBar", () => {
  it("shows the status and every action on desktop", () => {
    show(draft());
    const bar = screen.getByRole("region", { name: "Draft" });
    expect(within(bar).getByText("Unpublished changes to version 4")).toBeInTheDocument();
    for (const name of ["Discard changes", "Test a title", "Replay draft", "Publish"]) {
      expect(within(bar).getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("is one row on phones, with the other actions in a sheet and the whole status for screen readers", async () => {
    setScreen(390);
    const user = userEvent.setup();
    const current = draft();
    const { onTestTitle } = show(current);
    const bar = screen.getByRole("region", { name: "Draft" });
    expect(within(bar).getAllByRole("button").map((button) => button.getAttribute("aria-label") ?? button.textContent))
      .toEqual(["More draft actions", "Publish"]);
    // The short line is for the eye; screen readers hear the whole status, and hear it change.
    expect(within(bar).getByText("Valid, not replayed yet").closest("[aria-hidden]")).toHaveAttribute("aria-hidden", "true");
    expect(bar.querySelector("[aria-live]")).toHaveTextContent("Valid. Not replayed yet.");

    await user.click(within(bar).getByRole("button", { name: "More draft actions" }));
    const sheet = screen.getByRole("dialog", { name: "Unpublished changes to version 4" });
    expect(within(sheet).getByText("Valid. Not replayed yet.")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Test a title" }));
    expect(onTestTitle).toHaveBeenCalled();
    // The page behind a sheet is hidden from screen readers until the sheet has slid away.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(within(bar).getByRole("button", { name: "More draft actions" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Discard changes" }));
    expect(current.discard).toHaveBeenCalled();
  });

  it("offers to keep or discard an outdated draft from its menu on tablets", async () => {
    setScreen(700);
    const user = userEvent.setup();
    const current = draft({ outdated: true });
    show(current);
    await user.click(screen.getByRole("button", { name: "More draft actions" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent))
      .toEqual(["Keep my draft", "Discard it", "Replay draft", "Test a title"]);
    await user.click(screen.getByRole("menuitem", { name: "Keep my draft" }));
    expect(current.rebase).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("says in the sheet why Publish is off, since tooltips do not open from a tap", async () => {
    setScreen(390);
    const user = userEvent.setup();
    show(draft(), false);
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "More draft actions" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("You need Manage Channels in this search's channel to publish.");
  });

  it("stays out of sight on phones when there is nothing to do, but still tells screen readers the status", () => {
    setScreen(390);
    show(draft({ edited: false }));
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    const bar = screen.getByRole("region", { name: "Draft" });
    expect(bar).toHaveTextContent("Same as published version 4");
    expect(bar.querySelector("[aria-live]")).toHaveTextContent("Valid.");
  });

  it("steps aside while the on-screen keyboard is up", () => {
    setScreen(390);
    showKeyboard();
    show(draft());
    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
    act(() => screen.getByRole("textbox", { name: "Group name" }).focus());
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Draft" }).querySelector("[aria-live]")).toHaveTextContent("Valid. Not replayed yet.");
    act(() => screen.getByRole("textbox", { name: "Group name" }).blur());
    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
  });
});
