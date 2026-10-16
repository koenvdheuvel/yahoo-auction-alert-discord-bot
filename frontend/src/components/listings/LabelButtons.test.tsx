import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { Label } from "../../api/types";
import { LabelButtons } from "./LabelButtons";

function Harness({ initial = null }: { initial?: Label | null }) {
  const [value, setValue] = useState<Label | null>(initial);
  return <LabelButtons value={value} onChange={setValue} subject="beatmania IIDX B1 poster" />;
}

describe("LabelButtons", () => {
  it("names the group after the listing and marks the chosen label", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByRole("group", { name: "Label for beatmania IIDX B1 poster" })).toBeInTheDocument();
    const relevant = screen.getByRole("button", { name: "Relevant" });
    expect(relevant).toHaveAttribute("aria-pressed", "false");
    await user.click(relevant);
    expect(relevant).toHaveAttribute("aria-pressed", "true");
  });

  it("removes the label when the chosen one is pressed again", async () => {
    const user = userEvent.setup();
    render(<Harness initial="accessory" />);
    const accessory = screen.getByRole("button", { name: "Accessory" });
    await user.click(accessory);
    expect(accessory).toHaveAttribute("aria-pressed", "false");
    expect(screen.getAllByRole("button").filter((button) => button.getAttribute("aria-pressed") === "true")).toHaveLength(0);
  });
});
