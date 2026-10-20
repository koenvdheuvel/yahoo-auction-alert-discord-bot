import { ThemeProvider } from "@mui/material/styles";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RuleGroup } from "../../api/types";
import { theme } from "../../theme";
import { GroupEditor } from "./GroupEditor";
import { setScreen } from "../../test/screen";

const GROUP: RuleGroup = {
  id: "g1", label: "Extras", policy: "exclude", match: "any", normalize: true,
  terms: [{ method: "contains", value: "towel" }, { method: "contains", value: "sticker" }],
};

function show() {
  const handlers = { onChange: vi.fn(), onMove: vi.fn(), onDuplicate: vi.fn(), onRemove: vi.fn() };
  render(
    <ThemeProvider theme={theme}>
      <GroupEditor group={GROUP} index={0} count={2} error={null} cannotAdd={() => null} {...handlers} />
    </ThemeProvider>,
  );
  return handlers;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GroupEditor", () => {
  it("opens the group's actions as a menu on desktop", async () => {
    const user = userEvent.setup();
    const { onDuplicate } = show();
    await user.click(screen.getByRole("button", { name: "More actions for Extras" }));
    expect(screen.getByRole("menuitem", { name: "Move up" })).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("menuitem", { name: "Duplicate" }));
    expect(onDuplicate).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Any term" })).toHaveTextContent("Any term");
  });

  it("opens the group's actions as a sheet on phones, and keeps the full names of Any and All", async () => {
    setScreen(390);
    const user = userEvent.setup();
    const { onRemove } = show();
    // The toggle reads "Any" and "All" to fit next to the role; screen readers still hear "Any term".
    expect(screen.getByRole("button", { name: "Any term" })).toHaveTextContent(/^Any$/);
    await user.click(screen.getByRole("button", { name: "More actions for Extras" }));
    const sheet = screen.getByRole("dialog", { name: "Extras" });
    expect(within(sheet).getByRole("button", { name: "Move up" })).toHaveAttribute("aria-disabled", "true");
    await user.click(within(sheet).getByRole("button", { name: "Delete group" }));
    expect(onRemove).toHaveBeenCalled();
  });

  it("edits a term in a sheet on phones", async () => {
    setScreen(390);
    const user = userEvent.setup();
    const { onChange } = show();
    await user.click(screen.getByRole("button", { name: "Contains: sticker. Select to edit." }));
    const sheet = screen.getByRole("dialog", { name: "Edit term" });
    const field = within(sheet).getByRole("textbox", { name: "Term" });
    // The keyboard would cover the sheet, so the field waits for a tap.
    expect(field).not.toHaveFocus();
    await user.clear(field);
    await user.type(field, "stickers");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...GROUP, terms: [GROUP.terms[0], { method: "contains", value: "stickers" }] });
  });

  it("adds a term with the square Add button on phones", async () => {
    setScreen(390);
    const user = userEvent.setup();
    const { onChange } = show();
    await user.type(screen.getByRole("textbox", { name: "Add a term" }), "poster");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...GROUP, terms: [...GROUP.terms, { method: "contains", value: "poster" }] });
  });
});
