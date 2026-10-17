import type { AlertSummary, ChannelKind, ChannelList, ChannelRow, GuildSummary } from "../api/types";
import { plural } from "./format";
import type { ChannelTab } from "./hooks";

export const KIND_NAMES: Record<ChannelKind, string> = {
  text: "Text channel",
  announcement: "Announcement channel",
  forum: "Forum",
  media: "Media channel",
  voice: "Voice channel",
  stage: "Stage channel",
  thread: "Thread",
  private_thread: "Private thread",
  other: "Channel",
};

export const isThread = (channel: Pick<ChannelRow, "kind">) => channel.kind === "thread" || channel.kind === "private_thread";

/** Every channel and thread of the list, in the order the sidebar shows them. */
export function allChannels(list: ChannelList | undefined): ChannelRow[] {
  if (!list) return [];
  return list.sections.flatMap((section) => section.channels.flatMap((channel) => [channel, ...(channel.threads ?? [])]));
}

export function findChannel(list: ChannelList | undefined, channelId: string | null): ChannelRow | null {
  if (!channelId) return null;
  return allChannels(list).find((channel) => channel.id === channelId) ?? null;
}

/** Where a new search can go: channels the bot can post in and you may change. */
export function postableChannels(list: ChannelList | undefined): ChannelRow[] {
  return allChannels(list).filter((channel) => channel.posting.can_post && channel.can_manage);
}

/** Why the bot cannot post a search's listings here, in one sentence, or null when it can. */
export function postingProblem(channel: Pick<ChannelRow, "posting">): string | null {
  const { posting } = channel;
  if (posting.can_post) return null;
  if (posting.problems.length) return posting.problems.join(" ");
  return `The bot needs ${posting.missing.join(", ")} here.`;
}

/** "#posters" for a known channel, otherwise the end of its ID. */
export function channelLabel(channelId: string, name: string | null | undefined): string {
  return name ? `#${name}` : `Channel …${channelId.slice(-6)}`;
}

/** The searches of one server, by channel ID. */
export function searchesByChannel(alerts: AlertSummary[] | undefined, guildId: string | null): Map<string, AlertSummary[]> {
  const byChannel = new Map<string, AlertSummary[]>();
  for (const alert of alerts ?? []) {
    if (guildId !== null && alert.guild_id !== guildId) continue;
    const list = byChannel.get(alert.channel_id) ?? [];
    list.push(alert);
    byChannel.set(alert.channel_id, list);
  }
  for (const list of byChannel.values()) list.sort((left, right) => left.search_query.localeCompare(right.search_query));
  return byChannel;
}

/** A server's problems in words, for its tooltip and its badge's label. */
export function guildProblems(guild: GuildSummary): string[] {
  const problems = [];
  if (guild.failing_searches) problems.push(`${plural(guild.failing_searches, "search", "searches")} failed the last check`);
  if (guild.failed_deliveries) problems.push(`${plural(guild.failed_deliveries, "post or DM", "posts or DMs")} could not be sent`);
  return problems;
}

/** Whether you may change a search: Manage Channels in its channel, or its channel is gone. */
export function canChangeSearch(channels: ChannelList | undefined, alert: AlertSummary): boolean {
  const channel = findChannel(channels, alert.channel_id);
  if (channel) return channel.can_manage;
  return Boolean(channels?.unknown.some((item) => item.id === alert.channel_id && item.deleted));
}

/** A channel that is gone, or that Discord does not show the bot, has no posts to look at. */
export function channelTabs(known: boolean): ChannelTab[] {
  return known ? ["searches", "posts", "hidden", "cleanup"] : ["searches", "hidden"];
}
