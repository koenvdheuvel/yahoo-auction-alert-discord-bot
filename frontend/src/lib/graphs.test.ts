import { describe, expect, it } from "vitest";

import { durationTicks, formatGraphValue, formatTableValue, legendName, seriesNames, sharedSearchChannels } from "./graphs";

describe("formatGraphValue", () => {
  it("writes durations in the largest sensible unit", () => {
    expect(formatGraphValue(0, "s")).toBe("0 s");
    expect(formatGraphValue(0.25, "s")).toBe("250 ms");
    expect(formatGraphValue(0.999, "s")).toBe("999 ms");
    expect(formatGraphValue(1, "s")).toBe("1 s");
    expect(formatGraphValue(59, "s")).toBe("59 s");
    expect(formatGraphValue(60, "s")).toBe("1 min");
    expect(formatGraphValue(3599, "s")).toBe("60 min");
    expect(formatGraphValue(7200, "s")).toBe("2 h");
  });

  it("writes request rates per second", () => {
    expect(formatGraphValue(0.5, "reqps")).toBe("0.5/s");
    expect(formatGraphValue(12, "reqps")).toBe("12/s");
  });

  it("writes counts compactly and honors fixed decimals", () => {
    expect(formatGraphValue(48, "short")).toBe("48");
    expect(formatGraphValue(2.94, "none")).toBe("2.94");
    expect(formatGraphValue(1234, "short")).toBe("1.23K");
    expect(formatGraphValue(2, "short", 1)).toBe("2.0");
  });

  it("writes bytes in binary units", () => {
    expect(formatGraphValue(512, "bytes")).toBe("512 B");
    expect(formatGraphValue(1024, "bytes")).toBe("1 KB");
    expect(formatGraphValue(5 * 1024 ** 2, "bytes")).toBe("5 MB");
    expect(formatGraphValue(3 * 1024 ** 3, "bytes")).toBe("3 GB");
  });

  it("shows unknown units as plain numbers and gaps as nothing", () => {
    expect(formatGraphValue(1234.5678, "percentunit")).toBe("1,234.568");
    expect(formatGraphValue(null, "short")).toBe("");
  });
});

describe("formatTableValue", () => {
  it("rounds to the panel's decimals", () => {
    expect(formatTableValue(48, null)).toBe("48");
    expect(formatTableValue(1.2345, null)).toBe("1.23");
    expect(formatTableValue(3, 1)).toBe("3.0");
    expect(formatTableValue(null, 0)).toBe("");
  });
});

describe("durationTicks", () => {
  const series = (...values: (number | null)[]) => ({ legend: "", labels: {}, values });

  it("steps by a round duration up to the largest value", () => {
    expect(durationTicks([series(100, null, 3300), series(1200)], false)).toEqual([0, 900, 1800, 2700, 3600]);
    expect(durationTicks([series(3600)], false)).toEqual([0, 900, 1800, 2700, 3600]);
  });

  it("reaches the highest stack when the series are stacked", () => {
    const stack = [series(600, 300), series(700, 100)];
    expect(durationTicks(stack, true)).toEqual([0, 600, 1200, 1800]);
    expect(durationTicks(stack, false)).toEqual([0, 300, 600, 900]);
  });

  it("leaves the ticks to the chart when it cannot pick round ones", () => {
    expect(durationTicks([], false)).toBeNull();
    expect(durationTicks([series(null, 0)], false)).toBeNull();
    expect(durationTicks([series(5, -1)], false)).toBeNull();
    expect(durationTicks([series(5 * 86400)], false)).toBeNull();
  });
});

describe("legendName", () => {
  it("replaces labels with friendly values", () => {
    expect(legendName("{{source}} {{outcome}}", { source: "yahooauction", outcome: "http_error" })).toBe("Yahoo Auctions HTTP error");
  });

  it("falls back to the raw value with underscores as spaces", () => {
    expect(legendName("{{outcome}}", { outcome: "brand_new" })).toBe("brand new");
  });

  it("drops labels the series does not have and tidies spaces", () => {
    expect(legendName("{{source}}  {{missing}}", { source: "mercari" })).toBe("Mercari");
  });
});

describe("seriesNames", () => {
  it("uses the label values when the legend is empty", () => {
    expect(seriesNames("Title", [{ legend: "", labels: { source: "mercari", outcome: "success" }, values: [] }])).toEqual(["Mercari OK"]);
  });

  it("uses the panel title when nothing else is left", () => {
    expect(seriesNames("Title", [{ legend: "", labels: {}, values: [] }])).toEqual(["Title"]);
  });

  it("tells equal names apart by search", () => {
    const names = seriesNames("T", [
      { legend: "{{source}}", labels: { source: "mercari", search_query: "A", alert_id: "1" }, values: [] },
      { legend: "{{source}}", labels: { source: "mercari", search_query: "B", alert_id: "2" }, values: [] },
    ]);
    expect(names).toEqual(["Mercari (A)", "Mercari (B)"]);
  });

  it("tells searches with the same text apart by channel", () => {
    const channels = sharedSearchChannels([
      { id: "1", search_query: "A", channel_id: "31", channel_name: "posters" },
      { id: "2", search_query: "A", channel_id: "32", channel_name: null },
      { id: "3", search_query: "B", channel_id: "31", channel_name: "posters" },
    ]);
    expect(channels).toEqual({ 1: "#posters", 2: "Channel …32" });
    const series = (alertId: string, query: string) => ({ legend: "{{search_query}} {{source}}", labels: { source: "mercari", search_query: query, alert_id: alertId }, values: [] });
    expect(seriesNames("T", [series("1", "A"), series("2", "A"), series("3", "B")], channels))
      .toEqual(["A Mercari (#posters)", "A Mercari (Channel …32)", "B Mercari"]);
  });
});
