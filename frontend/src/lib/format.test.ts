import { describe, expect, it } from "vitest";

import { formatPrice, formatRelative, plural, safeUrl } from "./format";

describe("safeUrl", () => {
  it.each([
    ["https://jp.mercari.com/item/m123", "https://jp.mercari.com/item/m123"],
    ["http://example.com/a b", "http://example.com/a%20b"],
    ["javascript:alert(1)", null],
    ["data:text/html,<b>x</b>", null],
    ["/relative/path", null],
    ["", null],
    [null, null],
  ])("treats %s as %s", (value, expected) => {
    expect(safeUrl(value)).toBe(expected);
  });
});

describe("formatPrice", () => {
  it("shows yen, or says the price is missing", () => {
    expect(formatPrice(12500)).toBe("￥12,500");
    expect(formatPrice(null)).toBe("No price");
    expect(formatPrice(Number.NaN)).toBe("No price");
  });
});

describe("formatRelative", () => {
  const now = Date.parse("2026-10-16T12:00:00Z");

  it("picks the largest whole unit", () => {
    expect(formatRelative("2026-10-16T11:59:30Z", now)).toBe("just now");
    expect(formatRelative("2026-10-16T09:00:00Z", now)).toMatch(/3 hr\. ago|3 hours ago/);
    expect(formatRelative("2026-10-14T12:00:00Z", now)).toMatch(/2 days ago/);
  });

  it("does not throw on a bad timestamp", () => {
    expect(formatRelative("not a date", now)).toBe("unknown");
    expect(formatRelative(null, now)).toBe("unknown");
  });
});

describe("plural", () => {
  it("counts with the right noun", () => {
    expect(plural(1, "listing")).toBe("1 listing");
    expect(plural(1200, "listing")).toBe("1,200 listings");
    expect(plural(2, "listing was", "listings were")).toBe("2 listings were");
  });
});
