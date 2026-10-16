import type { RemovablePost, RemovalDays } from "../api/types";

export const REMOVAL_RANGES: { days: RemovalDays; label: string }[] = [
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: null, label: "All time" },
];

/** The posts to remove: this run's posts, except the ones whose reason the operator chose to keep. */
export function selectedPosts(posts: RemovablePost[], keptReasons: ReadonlySet<string>): string[] {
  return posts.filter((post) => !keptReasons.has(post.reason)).map((post) => post.message_id);
}

/** A link that opens the post in Discord; it needs the server's ID. */
export function discordLink(guildId: string | null, channelId: string, messageId: string): string | null {
  return guildId ? `https://discord.com/channels/${guildId}/${channelId}/${messageId}` : null;
}

/** The server's reason sentence as a short label. */
export function reasonLabel(message: string): string {
  return message.replace(/\.$/, "");
}
