import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";

import { claimDrafts } from "../lib/drafts";
import { canonical } from "../lib/ruleset";
import { ApiError, api, type CandidateQuery } from "./client";
import type { Candidate, CandidatePage, Label, RemovalDays, Ruleset, Session } from "./types";

export const PAGE_SIZE = 48;

export const keys = {
  session: ["session"] as const,
  guilds: ["guilds"] as const,
  channels: (guildId: string) => ["channels", guildId] as const,
  allChannels: ["channels"] as const,
  status: (guildId: string) => ["status", guildId] as const,
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
  return useQuery({ queryKey: keys.alerts, queryFn: ({ signal }) => api.alerts(signal), staleTime: 30_000, enabled });
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
    // While another filter loads, keep showing the previous results of the same search
    // instead of flashing placeholders; another search or server starts empty.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1].alertId === query.alertId && previousQuery.queryKey[1].guildId === query.guildId
        ? previous : undefined,
  });
}

type Pages = InfiniteData<CandidatePage, string | null>;

/** Sets labels in every loaded list without moving rows, and keeps the label counts right. */
function applyLabels(client: QueryClient, labels: Map<string, Label | null>) {
  client.setQueriesData<Pages>({ queryKey: keys.allCandidates }, (data) => {
    if (!data) return data;
    let facets = data.pages[0]?.facets;
    const pages = data.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => {
        if (!labels.has(item.id)) return item;
        const next = labels.get(item.id) ?? null;
        if (item.feedback === next) return item;
        if (facets) {
          const before = item.feedback ?? "unlabeled";
          const after = next ?? "unlabeled";
          facets = { ...facets, feedback: { ...facets.feedback, [before]: facets.feedback[before] - 1, [after]: facets.feedback[after] + 1 } };
        }
        return { ...item, feedback: next };
      }),
    }));
    if (pages[0] && facets) pages[0] = { ...pages[0], facets };
    return { ...data, pages };
  });
}

function currentLabels(client: QueryClient, ids: string[]): Map<string, Label | null> {
  const wanted = new Set(ids);
  const found = new Map<string, Label | null>();
  for (const [, data] of client.getQueriesData<Pages>({ queryKey: keys.allCandidates })) {
    for (const item of data?.pages.flatMap((page) => page.items) ?? []) {
      if (wanted.has(item.id) && !found.has(item.id)) found.set(item.id, item.feedback);
    }
  }
  return found;
}

export interface LabelChange {
  ids: string[];
  label: Label | null;
}

/** dashboard.py accepts at most this many listings per bulk label request. */
export const LABEL_BATCH = 200;

export function useLabelMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ ids, label }: LabelChange) => {
      if (ids.length === 1) return { items: [await api.label(ids[0]!, label)], missing: [] as string[] };
      const result = { items: [] as Candidate[], missing: [] as string[] };
      for (let start = 0; start < ids.length; start += LABEL_BATCH) {
        const part = await api.labelMany(ids.slice(start, start + LABEL_BATCH), label);
        result.items.push(...part.items);
        result.missing.push(...part.missing);
      }
      return result;
    },
    onMutate: async ({ ids, label }) => {
      await client.cancelQueries({ queryKey: keys.allCandidates });
      const previous = currentLabels(client, ids);
      applyLabels(client, new Map(ids.map((id) => [id, label])));
      return { previous };
    },
    onError: (_error, _change, context) => {
      if (context) applyLabels(client, context.previous);
      // Batches before the failed one were saved, so reload what the server has.
      void client.invalidateQueries({ queryKey: keys.allCandidates });
    },
    onSuccess: ({ items }) => {
      applyLabels(client, new Map(items.map((item: Candidate) => [item.id, item.feedback])));
    },
    onSettled: () => client.invalidateQueries({ queryKey: keys.alerts }),
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
