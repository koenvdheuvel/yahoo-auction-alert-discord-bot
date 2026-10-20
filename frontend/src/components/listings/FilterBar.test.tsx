import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Facets } from "../../api/types";
import type { ListingFilters } from "../views/SearchView";
import { FilterBar } from "./FilterBar";
import { setPhone } from "../../test/screen";

const FILTERS: ListingFilters = { search: "", source: "", verdict: "", latest: true };
const FACETS: Facets = { verdict: { accepted: 318, filtered: 80, review: 0 } };

function show(filters: Partial<ListingFilters> = {}) {
  const onFilters = vi.fn();
  render(<FilterBar filters={{ ...FILTERS, ...filters }} onFilters={onFilters} facets={FACETS} searchRef={{ current: null }} />);
  return onFilters;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FilterBar on a phone", () => {
  it("picks a decision from a sheet that shows each one's count", async () => {
    setPhone();
    const user = userEvent.setup();
    const onFilters = show();

    await user.click(screen.getByRole("button", { name: "Decision: Any decision" }));
    const sheet = screen.getByRole("dialog", { name: "Decision" });
    const rows = within(sheet).getAllByRole("menuitemradio");
    expect(rows.map((row) => row.textContent)).toEqual(["Any decision398", "Allowed318", "Filtered80", "Needs review0"]);
    expect(rows[0]).toHaveAttribute("aria-checked", "true");

    await user.click(rows[2]!);
    expect(onFilters).toHaveBeenCalledWith({ ...FILTERS, verdict: "filtered" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the current choices on the chips and turns earlier decisions on and off", async () => {
    setPhone();
    const user = userEvent.setup();
    const onFilters = show({ source: "mercari", verdict: "filtered" });

    expect(screen.getByRole("button", { name: "Decision: Filtered (80)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Marketplace: Mercari" }));
    const sheet = screen.getByRole("dialog", { name: "Marketplace" });
    expect(within(sheet).getByRole("menuitemradio", { name: "Mercari" })).toHaveAttribute("aria-checked", "true");
    await user.click(within(sheet).getByRole("menuitemradio", { name: "All marketplaces" }));
    expect(onFilters).toHaveBeenLastCalledWith({ ...FILTERS, verdict: "filtered", source: "" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    const earlier = screen.getByRole("button", { name: "Earlier decisions" });
    expect(earlier).toHaveAttribute("aria-pressed", "false");
    await user.click(earlier);
    expect(onFilters).toHaveBeenLastCalledWith({ ...FILTERS, source: "mercari", verdict: "filtered", latest: false });
  });

  it("clears the search with one tap", async () => {
    setPhone();
    const user = userEvent.setup();
    const onFilters = show({ search: "towel" });

    await user.click(screen.getByRole("button", { name: "Clear the search" }));
    expect(onFilters).toHaveBeenCalledWith(FILTERS);
  });
});

describe("FilterBar on a desktop", () => {
  it("keeps the decisions as buttons with their counts", () => {
    show();
    const decisions = screen.getByRole("group", { name: "Decision" });
    expect(within(decisions).getByRole("button", { name: /^Allowed\s*318$/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear the search" })).toBeNull();
  });
});
