const yen = new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" });
const count = new Intl.NumberFormat();
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style: "short" });

export function formatPrice(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? yen.format(value) : "No price";
}

export function formatCount(value: number): string {
  return count.format(value);
}

/** "1 listing", "2 listings". */
export function plural(value: number, singular: string, pluralForm = `${singular}s`): string {
  return `${formatCount(value)} ${value === 1 ? singular : pluralForm}`;
}

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

export function formatDateTime(value: string | null | undefined): string {
  const parsed = parse(value);
  return parsed ? dateTime.format(parsed) : "Unknown time";
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  const parsed = parse(value);
  if (!parsed) return "unknown";
  const seconds = Math.round((parsed.valueOf() - now) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

/** Only http(s) links are rendered; listing facts come from third-party marketplaces. */
export function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
