import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { canonical } from "../lib/ruleset";
import { ApiError, api, type CandidateQuery } from "./client";
import type { RemovalDays, Ruleset } from "./types";

export const PAGE_SIZE = 48;

export const keys = {
  session: ["session"] as const,
  alerts: ["alerts"] as const,
  rules: (alertId: string) => ["rules", alertId] as const,
  candidates: (query: CandidateQuery) => ["candidates", query] as const,
  allCandidates: ["candidates"] as const,
  removalStatus: (alertId: string) => ["removal-status", alertId] as const,
};

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
    refetchInterval: (query) => (query.state.data?.run?.pending ? 5000 : false),
  });
}

export function useSession() {
  return useQuery({ queryKey: keys.session, queryFn: ({ signal }) => api.session(signal), staleTime: 60_000 });
}

export function useAlerts() {
  return useQuery({ queryKey: keys.alerts, queryFn: ({ signal }) => api.alerts(signal), staleTime: 30_000 });
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
    // instead of flashing placeholders; another search starts empty.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1].alertId === query.alertId ? previous : undefined,
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
