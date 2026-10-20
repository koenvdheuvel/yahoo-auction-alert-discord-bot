import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { claimDrafts } from "../lib/drafts";
import { canonical } from "../lib/ruleset";
import { ApiError, UNREAD_BATCH, api } from "./client";
import type { CandidateQuery } from "./client";
import type { GraphRange, RemovalDays, Ruleset, Session } from "./types";

export const PAGE_SIZE = 48;

export const keys = {
  session: ["session"] as const,
  guilds: ["guilds"] as const,
  channels: (guildId: string) => ["channels", guildId] as const,
  allChannels: ["channels"] as const,
  status: (guildId: string) => ["status", guildId] as const,
  graphs: (guildId: string, range: GraphRange) => ["graphs", guildId, range] as const,
  alert: (alertId: string) => ["alert", alertId] as const,
  posts: (channelId: string, alertId: string | null) => ["posts", channelId, alertId] as const,
  allPosts: ["posts"] as const,
  hidden: (channelId: string) => ["hidden", channelId] as const,
  cleanupStatus: (channelId: string) => ["cleanup-status", channelId] as const,
  scan: (channelId: string) => ["history-scan", channelId] as const,
  notifications: ["notifications"] as const,
  alerts: ["alerts"] as const,
  rules: (alertId: string) => ["rules", alertId] as const,
  candidates: (query: CandidateQuery) => ["candidates", query] as const,
  allCandidates: ["candidates"] as const,
  removalStatus: (alertId: string) => ["removal-status", alertId] as const,
  unread: (owner: string, asks: UnreadAsk[]) => ["unread", owner, asks] as const,
};

/**
 * Something answered 404. It may be in a server the person just lost on Discord, so the session
 * and the searches are asked for again, which drops that server from the page.
 */
export function refreshAccess(client: QueryClient, error: unknown) {
  if (!(error instanceof ApiError) || error.status !== 404) return;
  void client.invalidateQueries({ queryKey: keys.session });
  void client.invalidateQueries({ queryKey: keys.alerts });
  void client.invalidateQueries({ queryKey: keys.guilds });
}

export function useGuilds() {
  return useQuery({ queryKey: keys.guilds, queryFn: ({ signal }) => api.guilds(signal), staleTime: 30_000 });
}

/** The server's channels in Discord's order. Discord changes come in with the next fetch. */
export function useChannels(guildId: string | null) {
  return useQuery({
    queryKey: keys.channels(guildId ?? "none"),
    queryFn: ({ signal }) => api.channels(guildId!, signal),
    enabled: guildId !== null,
    staleTime: 30_000,
  });
}

export function useGuildStatus(guildId: string | null) {
  return useQuery({
    queryKey: keys.status(guildId ?? "none"),
    queryFn: ({ signal }) => api.status(guildId!, signal),
    enabled: guildId !== null,
    refetchInterval: 30_000,
  });
}

export function useGuildGraphs(guildId: string, range: GraphRange) {
  return useQuery({
    queryKey: keys.graphs(guildId, range),
    queryFn: ({ signal }) => api.graphs(guildId, range, signal),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useAlertDetail(alertId: string | null, enabled = true) {
  return useQuery({
    queryKey: keys.alert(alertId ?? "none"),
    queryFn: ({ signal }) => api.alert(alertId!, signal),
    enabled: enabled && alertId !== null,
    staleTime: 0,
  });
}

export function usePosts(channelId: string, alertId: string | null) {
  return useInfiniteQuery({
    queryKey: keys.posts(channelId, alertId),
    queryFn: ({ pageParam, signal }) => api.posts(channelId, alertId, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before,
    staleTime: 15_000,
  });
}

export function useHidden(channelId: string) {
  return useQuery({ queryKey: keys.hidden(channelId), queryFn: ({ signal }) => api.hidden(channelId, signal) });
}

/** Progress of the channel's latest cleanup; checked again every few seconds while posts are waiting. */
export function useCleanupStatus(channelId: string) {
  return useQuery({
    queryKey: keys.cleanupStatus(channelId),
    queryFn: ({ signal }) => api.cleanupStatus(channelId, signal),
    refetchInterval: (query) => (query.state.status !== "error" && query.state.data?.run?.pending ? 5000 : false),
  });
}

export function useHistoryScan(channelId: string) {
  return useQuery({
    queryKey: keys.scan(channelId),
    queryFn: ({ signal }) => api.scanStatus(channelId, signal),
    refetchInterval: (query) => (query.state.data?.scan?.state === "running" ? 2000 : false),
  });
}

export function useNotifications(enabled: boolean) {
  return useQuery({ queryKey: keys.notifications, queryFn: ({ signal }) => api.notifications(signal), enabled });
}

/** After a change to searches, everything that counts them is asked for again. */
export function refreshSearches(client: QueryClient) {
  for (const key of [keys.alerts, keys.guilds, keys.allChannels, ["status"], ["alert"]]) {
    void client.invalidateQueries({ queryKey: key });
  }
}

/** Follow or stop following a listing with 🔔, and update every list that shows it. */
export function useSubscription() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, follow }: { itemId: string; follow: boolean }) =>
      follow ? api.subscribe(itemId) : api.unsubscribe(itemId),
    onSettled: () => {
      for (const key of [keys.notifications, keys.allPosts, keys.allCandidates]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}

/** The search's posts that `ruleset`, or the published rules when it is undefined, filter. */
export function useRemovalPreview(alertId: string | null, days: RemovalDays, ruleset: Ruleset | undefined, enabled: boolean) {
  const rules = ruleset ? JSON.stringify(canonical(ruleset)) : "published";
  return useQuery({
    queryKey: ["removal-preview", alertId, days, rules],
    queryFn: ({ signal }) => api.removalPreview(alertId!, days, ruleset, signal),
    enabled: enabled && alertId !== null,
    // Posts come and go with every check, so each opening checks again.
    staleTime: 0,
    gcTime: 0,
  });
}

/** Progress of the search's latest post removal; checked again every few seconds while posts are waiting. */
export function useRemovalStatus(alertId: string | null) {
  return useQuery({
    queryKey: keys.removalStatus(alertId ?? "none"),
    queryFn: ({ signal }) => api.removalStatus(alertId!, signal),
    enabled: alertId !== null,
    // Stops after an error such as a 404 for a server the person lost; the last good answer is not polled on.
    refetchInterval: (query) => (query.state.status !== "error" && query.state.data?.run?.pending ? 5000 : false),
  });
}

/** Who owns the drafts in this browser for a signed-in session. */
export function draftOwner(session: Session): string {
  return session.user?.id ?? "access_key";
}

export function useSession() {
  // Asking again now and then picks up servers the person gained or lost on Discord.
  return useQuery({
    queryKey: keys.session,
    queryFn: async ({ signal }) => {
      const session = await api.session(signal);
      // Before the workspace reads any draft, drop drafts another person left in this browser.
      if (session.authenticated) claimDrafts(draftOwner(session));
      return session;
    },
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}

/** The searches of the servers you manage. Off for someone who manages none: the server answers them 404. */
export function useAlerts(enabled = true) {
  return useQuery({ queryKey: keys.alerts, queryFn: ({ signal }) => api.alerts(signal), staleTime: 30_000,
    refetchInterval: 30_000, enabled });
}

/** A search whose listings may be unread: its ID, the listing it was read through (null: none yet) and its newest listing. */
export type UnreadAsk = readonly [alertId: string, readThrough: string | null, latestCandidateId: string];

/** What one count asked as well as what it answered, so an answer is only used for the cursors it was asked about. */
export interface UnreadAnswer {
  owner: string;
  asked: Record<string, string | null>;
  counts: Record<string, number>;
}

/**
 * How many listings of each search lie after this person's read cursor, in as many requests as the server's limit asks for.
 * The key holds the owner, every cursor and every newest listing: another person, a read search or a new listing asks again,
 * and a late answer lands under the key it was asked for, where nothing looks at it any more.
 */
export function useUnreadCounts(owner: string | null, asks: UnreadAsk[]) {
  return useQuery({
    queryKey: keys.unread(owner ?? "none", asks),
    queryFn: async ({ signal }): Promise<UnreadAnswer> => {
      const asked: Record<string, string | null> = {};
      for (const [alertId, readThrough] of asks) asked[alertId] = readThrough;
      const answers = await Promise.all(Array.from({ length: Math.ceil(asks.length / UNREAD_BATCH) }, (_, index) => {
        const batch: Record<string, string | null> = {};
        const end = Math.min((index + 1) * UNREAD_BATCH, asks.length);
        for (let row = index * UNREAD_BATCH; row < end; row++) {
          const [alertId, readThrough] = asks[row]!;
          batch[alertId] = readThrough;
        }
        return api.unreadCounts(batch, signal);
      }));
      const counts: Record<string, number> = {};
      for (const answer of answers) Object.assign(counts, answer.counts);
      return { owner: owner!, asked, counts };
    },
    enabled: owner !== null && asks.length > 0,
    // Searches whose cursor did not move keep their count while the new answer is on its way; the answer says which those are.
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    // Retention drops old listings without any new one arriving.
    refetchInterval: 60_000,
  });
}

export function useRules(alertId: string | null) {
  return useQuery({
    queryKey: keys.rules(alertId ?? "none"),
    queryFn: ({ signal }) => api.rules(alertId!, signal),
    enabled: alertId !== null,
    staleTime: 30_000,
  });
}

export function useCandidates(query: CandidateQuery) {
  return useInfiniteQuery({
    queryKey: keys.candidates(query),
    queryFn: ({ pageParam, signal }) => api.candidates(query, pageParam, PAGE_SIZE, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 30_000,
    // While another filter loads, keep showing the previous results of the same search or server
    // instead of flashing placeholders; another search, channel or server starts empty.
    placeholderData: (previous, previousQuery) => {
      const before = previousQuery?.queryKey[1];
      return before?.alertId === query.alertId && before.guildId === query.guildId && before.channelId === query.channelId
        ? previous : undefined;
    },
  });
}

export type Validation =
  | { state: "valid"; ruleset: Ruleset }
  | { state: "invalid"; message: string; field: string | undefined };

/** Server-side validation of a serialized draft; regex syntax and limits are the server's to judge. */
export function useValidation(serialized: string | null) {
  return useQuery({
    queryKey: ["validate", serialized],
    queryFn: async ({ signal }): Promise<Validation> => {
      try {
        return { state: "valid", ruleset: (await api.validate(JSON.parse(serialized!) as Ruleset, signal)).ruleset };
      } catch (error) {
        if (error instanceof ApiError && error.status === 400) {
          return { state: "invalid", message: error.message, field: error.field };
        }
        throw error;
      }
    },
    enabled: serialized !== null,
    staleTime: Infinity,
    retry: false,
    placeholderData: keepPreviousData,
  });
}
