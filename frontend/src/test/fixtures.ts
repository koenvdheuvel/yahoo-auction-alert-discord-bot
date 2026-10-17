import type { AlertSummary, ChannelList, ChannelRow, Posting } from "../api/types";

export const POSTING: Posting = { can_post: true, missing: [], problems: [], bulk_delete: true, read_history: true };

export function channelRow(id: string, name: string, overrides: Partial<ChannelRow> = {}): ChannelRow {
  return { id, name, kind: "text", parent_id: null, archived: false, locked: false, searches: 0, hidden: 0,
    posting: POSTING, can_manage: true, threads: [], ...overrides };
}

export function alertSummary(id: string, channelId: string, query: string, guildId = "11"): AlertSummary {
  return { id, guild_id: guildId, channel_id: channelId, channel_name: null, search_query: query,
    archived_count: 1, listing_count: 3, accepted_count: 3, filtered_count: 0, review_count: 0, labeled_count: 0,
    last_seen_at: null, active_version_id: null, sources: ["yahooauction", "mercari", "surugaya", "rakuma"] };
}

/** A server like Discord would list it: one channel without a category, then two categories. */
export const CHANNELS: ChannelList = {
  guild: { id: "11", name: "Poster hunters", icon_url: null },
  source: "gateway",
  discord_unavailable: false,
  sections: [
    { category: null, channels: [channelRow("100", "welcome")] },
    { category: { id: "200", name: "Posters" }, channels: [
      channelRow("201", "posters-yahoo", { parent_id: "200", searches: 1, threads: [
        channelRow("203", "sold-out", { kind: "thread", parent_id: "201", searches: 1 }),
      ] }),
      channelRow("202", "quiet", { parent_id: "200", posting: { ...POSTING, can_post: false, missing: ["Add Reactions"] } }),
      channelRow("204", "staff", { parent_id: "200", can_manage: false }),
    ] },
    { category: { id: "300", name: "Archive" }, channels: [channelRow("301", "old-posters", { parent_id: "300", hidden: 2 })] },
  ],
  unknown: [{ id: "999000000000000123", deleted: true, searches: 1, hidden: 0 }],
};
