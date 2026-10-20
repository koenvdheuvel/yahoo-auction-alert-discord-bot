import type {
  AlertDetail,
  AlertSummary,
  AlertsResponse,
  ChannelList,
  ChannelPosts,
  CleanupPreview,
  GraphRange,
  GuildGraphs,
  GuildStatus,
  GuildSummary,
  HiddenListings,
  HiddenSubscription,
  HistoryScan,
  ScanAction,
  SourcesChange,
  Subscription,
  CandidatePage,
  Decision,
  ImportResult,
  RemovalDays,
  RemovalPreview,
  RemovalResult,
  RemovalStatus,
  ReplayResult,
  RulesResponse,
  RuleVersion,
  Ruleset,
  Session,
  Source,
  Verdict,
} from "./types";

/** An error response from dashboard.py, or a network failure (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** For ruleset errors, the field at fault, such as "groups.1.terms.0". */
  readonly field: string | undefined;

  constructor(message: string, status: number, code: string, field?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

const sessionEndedListeners = new Set<(error: ApiError) => void>();

/** Runs when any request finds the session gone, so the app can ask the person to sign in again. */
export function onSessionEnded(listener: (error: ApiError) => void): () => void {
  sessionEndedListeners.add(listener);
  return () => sessionEndedListeners.delete(listener);
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function request<T>(path: string, { method = "GET", body, signal }: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError("The dashboard can't be reached. Check that the bot is running, then try again.", 0, "network_error");
  }
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const message = typeof data.message === "string" ? data.message : `The request failed with status ${response.status}.`;
    const code = typeof data.error === "string" ? data.error : "http_error";
    const error = new ApiError(message, response.status, code, typeof data.field === "string" ? data.field : undefined);
    if (response.status === 401 && path !== "/api/login") sessionEndedListeners.forEach((listener) => listener(error));
    throw error;
  }
  return data as T;
}

export interface CandidateQuery {
  alertId: string | null;
  /** All listings of one Discord server, when no alert is selected. */
  guildId: string | null;
  search: string;
  source: Source | "";
  verdict: Verdict | "";
  latest: boolean;
}

export const api = {
  session: (signal?: AbortSignal) => request<Session>("/api/session", { signal }),
  login: (token: string) => request<Session>("/api/login", { method: "POST", body: { token } }),
  logout: () => request<Session>("/api/session", { method: "DELETE", body: {} }),
  alerts: (signal?: AbortSignal) => request<AlertsResponse>("/api/alerts", { signal }),
  rules: (alertId: string, signal?: AbortSignal) =>
    request<RulesResponse>(`/api/alerts/${encodeURIComponent(alertId)}/rules`, { signal }),
  candidates(query: CandidateQuery, cursor: string | null, limit: number, signal?: AbortSignal) {
    const params = new URLSearchParams({ limit: String(limit), latest: query.latest ? "1" : "0" });
    if (query.alertId) params.set("alert_id", query.alertId);
    else if (query.guildId) params.set("guild_id", query.guildId);
    if (query.search) params.set("search", query.search);
    if (query.source) params.set("source", query.source);
    if (query.verdict) params.set("verdict", query.verdict);
    // Facet counts only change with the filters, so only the first page asks for them.
    if (cursor) params.set("cursor", cursor);
    else params.set("facets", "1");
    return request<CandidatePage>(`/api/candidates?${params.toString()}`, { signal });
  },
  validate: (ruleset: Ruleset, signal?: AbortSignal) =>
    request<{ ruleset: Ruleset }>("/api/rules/validate", { method: "POST", body: { ruleset }, signal }),
  preview: (body: { ruleset: Ruleset; title: string; source: Source; price: number; stock: number; alert_id?: string }) =>
    request<{ decision: Decision }>("/api/preview", { method: "POST", body }),
  replay: (alertId: string, ruleset: Ruleset) =>
    request<ReplayResult>("/api/replay", { method: "POST", body: { alert_id: alertId, ruleset } }),
  publish: (alertId: string, ruleset: Ruleset, expectedVersionId: string | null) =>
    request<RuleVersion>(`/api/alerts/${encodeURIComponent(alertId)}/publish`, {
      method: "POST",
      body: { ruleset, expected_version_id: expectedVersionId },
    }),
  restore: (alertId: string, versionId: string, expectedVersionId: string | null) =>
    request<RuleVersion>(`/api/alerts/${encodeURIComponent(alertId)}/rollback`, {
      method: "POST",
      body: { version_id: versionId, expected_version_id: expectedVersionId },
    }),
  importHistory: () => request<ImportResult>("/api/history/import", { method: "POST", body: {} }),
  /** The search's posts that `ruleset`, or else the published rules, filter. Changes nothing. */
  removalPreview: (alertId: string, days: RemovalDays, ruleset?: Ruleset, signal?: AbortSignal) =>
    request<RemovalPreview>(`/api/alerts/${encodeURIComponent(alertId)}/posts/removal-preview`, {
      method: "POST",
      body: ruleset ? { days, ruleset } : { days },
      signal,
    }),
  removePosts: (alertId: string, versionId: string, messageIds: string[]) =>
    request<RemovalResult>(`/api/alerts/${encodeURIComponent(alertId)}/posts/removal`, {
      method: "POST",
      body: { version_id: versionId, message_ids: messageIds },
    }),
  removalStatus: (alertId: string, signal?: AbortSignal) =>
    request<RemovalStatus>(`/api/alerts/${encodeURIComponent(alertId)}/posts/removal`, { signal }),

  guilds: (signal?: AbortSignal) => request<{ guilds: GuildSummary[] }>("/api/guilds", { signal }),
  channels: (guildId: string, signal?: AbortSignal) =>
    request<ChannelList>(`/api/guilds/${encodeURIComponent(guildId)}/channels`, { signal }),
  status: (guildId: string, signal?: AbortSignal) =>
    request<GuildStatus>(`/api/guilds/${encodeURIComponent(guildId)}/status`, { signal }),
  graphs: (guildId: string, range: GraphRange, signal?: AbortSignal) =>
    request<GuildGraphs>(`/api/guilds/${encodeURIComponent(guildId)}/graphs?range=${range}`, { signal }),
  /** /register in a channel. The server works out the channel's server with Discord. */
  register: (channelId: string, searchQuery: string) =>
    request<AlertSummary>("/api/alerts", { method: "POST", body: { channel_id: channelId, search_query: searchQuery } }),
  alert: (alertId: string, signal?: AbortSignal) =>
    request<AlertDetail>(`/api/alerts/${encodeURIComponent(alertId)}`, { signal }),
  unregister: (alertId: string) =>
    request<{ unregistered: boolean }>(`/api/alerts/${encodeURIComponent(alertId)}`, { method: "DELETE", body: {} }),
  setSources: (alertId: string, sources: Source[]) =>
    request<SourcesChange>(`/api/alerts/${encodeURIComponent(alertId)}/sources`, { method: "PUT", body: { sources } }),
  deleteLegacyFilter: (alertId: string, filterId: number) =>
    request<{ deleted: boolean }>(`/api/alerts/${encodeURIComponent(alertId)}/legacy-filters/${filterId}`,
      { method: "DELETE", body: {} }),
  posts: (channelId: string, alertId: string | null, before: string | null, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (alertId) params.set("alert_id", alertId);
    if (before) params.set("before", before);
    const query = params.toString();
    return request<ChannelPosts>(`/api/channels/${encodeURIComponent(channelId)}/posts${query ? `?${query}` : ""}`, { signal });
  },
  hidden: (channelId: string, signal?: AbortSignal) =>
    request<HiddenListings>(`/api/channels/${encodeURIComponent(channelId)}/hidden`, { signal }),
  hide: (channelId: string, itemId: string) =>
    request<{ hidden: boolean; posts_queued: number; bot_running: boolean }>(
      `/api/channels/${encodeURIComponent(channelId)}/hidden/${encodeURIComponent(itemId)}`, { method: "PUT", body: {} }),
  unhide: (channelId: string, itemId: string) =>
    request<{ hidden: boolean }>(`/api/channels/${encodeURIComponent(channelId)}/hidden/${encodeURIComponent(itemId)}`,
      { method: "DELETE", body: {} }),
  cleanupPreview: (channelId: string, days: RemovalDays, alertId: string | null, signal?: AbortSignal) =>
    request<CleanupPreview>(`/api/channels/${encodeURIComponent(channelId)}/posts/removal-preview`, {
      method: "POST", body: alertId ? { days, alert_id: alertId } : { days }, signal }),
  cleanup: (channelId: string, messageIds: string[]) =>
    request<RemovalResult>(`/api/channels/${encodeURIComponent(channelId)}/posts/removal`, {
      method: "POST", body: { message_ids: messageIds } }),
  cleanupStatus: (channelId: string, signal?: AbortSignal) =>
    request<RemovalStatus>(`/api/channels/${encodeURIComponent(channelId)}/posts/removal`, { signal }),
  startScan: (channelId: string, action: ScanAction, count?: number) =>
    request<{ scan: HistoryScan }>(`/api/channels/${encodeURIComponent(channelId)}/history-scan`, {
      method: "POST", body: count === undefined ? { action } : { action, count } }),
  scanStatus: (channelId: string, signal?: AbortSignal) =>
    request<{ scan: HistoryScan | null; available: boolean }>(
      `/api/channels/${encodeURIComponent(channelId)}/history-scan`, { signal }),
  notifications: (signal?: AbortSignal) =>
    request<{ items: (Subscription | HiddenSubscription)[] }>("/api/me/notifications", { signal }),
  subscribe: (itemId: string) =>
    request<{ subscribed: boolean; created: boolean }>(`/api/me/notifications/${encodeURIComponent(itemId)}`,
      { method: "PUT", body: {} }),
  unsubscribe: (itemId: string) =>
    request<{ subscribed: boolean }>(`/api/me/notifications/${encodeURIComponent(itemId)}`, { method: "DELETE", body: {} }),
};
