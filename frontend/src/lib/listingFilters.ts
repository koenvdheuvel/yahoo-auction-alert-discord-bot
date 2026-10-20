import type { CandidateQuery } from "../api/client";

/** A server's listings narrowed to one of its searches and/or channels; "" is all of them. */
export interface ListingScope {
  /** The server the choices were made in. Choices hold only there, so another server never shows a stale one. */
  guildId: string | null;
  alertId: string;
  channelId: string;
}

export type ListingFilters = Omit<CandidateQuery, "alertId" | "guildId" | "channelId"> & {
  /** Only a server's listings use it; one search's own listings ignore it. */
  scope: ListingScope | null;
};

export const DEFAULT_LISTING_FILTERS: ListingFilters = { search: "", source: "", verdict: "", latest: true, scope: null };
