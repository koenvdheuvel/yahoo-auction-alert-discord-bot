// Shapes returned by dashboard.py. IDs are strings because Discord snowflakes exceed 2^53.

export type Source = "yahooauction" | "mercari" | "surugaya" | "rakuma";
export type Verdict = "accepted" | "filtered" | "review";
export type Policy = "require" | "exclude" | "review";
export type TermMethod = "contains" | "exact" | "regex";

/** How this dashboard signs people in: with Discord, or with the access key when Discord sign-in is not set up. */
export type SignInMethod = "discord" | "access_key";

export interface DiscordUser {
  id: string;
  name: string;
  username: string;
  avatar_url: string;
}

/** A manager has Manage Channels for the whole server; a member only manages their own 🔔 notifications. */
export type Level = "manager" | "member";

/** A Discord server of the bot that the signed-in person is in. */
export interface Guild {
  id: string;
  name: string;
  icon_url: string | null;
  level?: Level;
}

/** The bot as Discord shows it. */
export interface BotUser {
  id: string;
  name: string;
  avatar_url: string;
}

export interface Session {
  authenticated: boolean;
  method?: SignInMethod;
  /** The dashboard's name, such as "PosterFinder Dashboard". */
  title?: string;
  bot?: BotUser | null;
  /** Whether this process is the bot itself, which sends and removes posts. */
  bot_running?: boolean;
  /** Set when this check found that the person lost access to every server. */
  reason?: "access_revoked";
  expires_in?: number;
  replay_limit?: number;
  /** Null when signed in with the access key. */
  user?: DiscordUser | null;
  /** The servers this person may see; null with the access key, which sees every server. */
  guilds?: Guild[] | null;
  features?: { notifications: boolean; discord_data: boolean };
  /** The marketplaces the bot searches at all (the operator's ENABLE_* settings). A search's own choice only has effect for these. */
  enabled_sources?: Source[];
}

/** A server in the server list. Its name is null when only its ID is known. The counts are only there
 * for servers you manage. */
export interface GuildSummary {
  id: string;
  name: string | null;
  icon_url: string | null;
  level: Level;
  searches?: number;
  failing_searches?: number;
  failed_deliveries?: number;
}

export type ChannelKind = "text" | "announcement" | "forum" | "media" | "voice" | "stage" | "thread" | "private_thread" | "other";

/** Whether the bot can post a search's listings in a channel. */
export interface Posting {
  can_post: boolean;
  /** Discord permission names the bot lacks there, such as "Add Reactions". */
  missing: string[];
  problems: string[];
  bulk_delete: boolean;
  read_history: boolean;
}

export interface ChannelRow {
  id: string;
  name: string;
  kind: ChannelKind;
  parent_id: string | null;
  archived: boolean;
  locked: boolean;
  searches: number;
  hidden: number;
  posting: Posting;
  /** Whether you have Manage Channels there, which changes need. */
  can_manage: boolean;
  threads?: ChannelRow[];
}

export interface UnknownChannel {
  id: string;
  /** True when Discord said the channel no longer exists. */
  deleted: boolean;
  searches: number;
  hidden: number;
}

export interface ChannelList {
  guild: { id: string; name: string | null; icon_url: string | null };
  /** Where the list came from: the bot's gateway cache, Discord's REST API, or nowhere. */
  source: "gateway" | "rest" | "none";
  discord_unavailable: boolean;
  sections: { category: { id: string; name: string } | null; channels: ChannelRow[] }[];
  unknown: UnknownChannel[];
}

export interface CheckResult {
  source: Source;
  outcome: "success" | "error" | "timeout";
  /** Seconds since 1970. */
  finished_at: number;
  duration_seconds: number;
  error: string | null;
}

export interface Backlog {
  pending: number;
  failed: number;
  oldest_pending_seconds: number | null;
}

export interface SearchStatus extends AlertSummary {
  /** Null when the bot does not run in this process. */
  checks: CheckResult[] | null;
  backlog: Backlog;
}

export interface BotStatus {
  ready: boolean;
  discord_connected: boolean;
  database_available: boolean;
  failed_worker: string | null;
  last_poll_at: number | null;
  last_success_at: number | null;
  started_at: number | null;
  interval_seconds: number;
  sources: Record<string, number | null>;
}

export interface GuildStatus {
  bot_running: boolean;
  bot: BotStatus | null;
  enabled_sources: Source[];
  interval_seconds: number;
  searches: SearchStatus[];
  totals: { searches: number; pending: number; failed: number };
}

/** What unregistering a search touches. */
export interface AlertUsage {
  posts: number;
  waiting_posts: number;
  rule_versions: number;
  archived: number;
  legacy_filters: number;
}

export interface AlertDetail {
  alert: AlertSummary;
  usage: AlertUsage;
  channel: { name: string; kind: ChannelKind; posting: Posting; can_manage: boolean } | null;
  channel_deleted: boolean;
}

/** A listing as the bot stored it. */
export interface StoredListing {
  item_id: string;
  source: string;
  external_id: string;
  title: string;
  price: number;
  buyout_price: number;
  stock: number;
  image_url: string | null;
  url: string | null;
  end_time: string | null;
  muted: boolean;
  updated_at: string | null;
  last_seen_at: string | null;
}

export interface ChannelPost {
  message_id: string;
  posted_at: string;
  alert_id: string | null;
  item_id: string;
  listing: { id: string; source: string; title: string; price: number; stock: number; buyout_price: number;
    image_url: string; url: string };
  hidden: boolean;
  subscribers: number;
  subscribed_by_me: boolean;
  queued: boolean;
}

export interface ChannelPosts {
  posts: ChannelPost[];
  next_before: string | null;
  /** Whether 🔔 works for you here: it needs Discord sign-in. */
  notifications: boolean;
}

export interface HiddenListings {
  items: StoredListing[];
  total: number;
}

export interface CleanupPost {
  message_id: string;
  posted_at: string;
  alert_id: string | null;
  title: string;
  source: string;
  external_id: string;
  price: number;
  image_url: string;
  url: string;
}

export interface CleanupPreview {
  days: RemovalDays;
  posts_in_range: number;
  removable_total: number;
  limit: number;
  bot_running: boolean;
  kept: { subscribed: number; queued: number };
  posts: CleanupPost[];
}

export type ScanAction = "delete_bot_posts" | "add_reactions";

export interface HistoryScan {
  action: ScanAction;
  count: number | null;
  state: "running" | "done" | "forbidden" | "failed";
  started_at: number;
  finished_at: number | null;
  done: number;
  history_limit: number;
}

export interface SubscriptionPost {
  channel_id: string;
  /** Null when the listing was only tracked there, not posted. */
  message_id: string | null;
  guild_id: string;
  search_query: string | null;
  channel_name: string;
}

export interface Subscription extends StoredListing {
  /** Where it was posted or tracked, in channels you can view now. */
  posts: SubscriptionPost[];
  waiting_dms: number;
  redacted?: false;
}

/** A listing you follow that is only in channels you cannot view, or in servers you left. */
export interface HiddenSubscription {
  item_id: string;
  redacted: true;
}

export interface AlertSummary {
  id: string;
  channel_id: string;
  guild_id: string | null;
  channel_name: string | null;
  search_query: string;
  archived_count: number;
  listing_count: number;
  accepted_count: number;
  filtered_count: number;
  review_count: number;
  last_seen_at: string | null;
  active_version_id: string | null;
  /** The marketplaces this search checks, in display order. */
  sources: Source[];
}

/** What turning marketplaces on or off for a search changed. */
export interface SourcesChange {
  sources: Source[];
  turned_on: Source[];
  turned_off: Source[];
}

export interface ArchiveTotals {
  archived_count: number;
  unassigned_count: number;
}

export interface AlertsResponse {
  alerts: AlertSummary[];
  totals: ArchiveTotals & { guilds: Record<string, ArchiveTotals> };
}

export interface Reason {
  code: string;
  message: string;
  group_id?: string;
}

export interface Decision {
  verdict: Verdict;
  allowed?: boolean;
  normalized_title: string;
  reasons: Reason[];
  matched_groups?: string[];
  legacy_matched_rules?: number[];
  normalization_version?: number;
  observation_kind?: string;
}

export interface ListingFacts {
  id?: string;
  source?: string;
  title?: string;
  price?: number | null;
  buyout_price?: number | null;
  stock?: number | null;
  url?: string;
  image_url?: string;
  end_time?: string | null;
  archive_truncated?: boolean;
}

export interface Candidate {
  id: string;
  alert_id: string | null;
  channel_id: string;
  search_query: string;
  source: string;
  external_id: string;
  title: string;
  normalized_title: string;
  payload: ListingFacts;
  decision: Decision;
  verdict: Verdict;
  ruleset_version_id: string | null;
  observation_kind: string;
  origin: "live" | "delivery_import" | "item_import";
  incomplete: boolean;
  observed_at: string;
  last_seen_at: string | null;
  /** The stored listing, which 🔔 follows. Null for listings the bot filtered and never stored. */
  item_id?: string | null;
  /** Whether you follow this listing with 🔔. */
  subscribed?: boolean;
}

export interface Facets {
  verdict: Record<Verdict, number>;
}

export interface CandidatePage {
  items: Candidate[];
  total: number;
  has_more: boolean;
  next_cursor: string | null;
  facets?: Facets;
}

export interface Term {
  method: TermMethod;
  value: string;
}

export interface RuleGroup {
  id: string;
  label: string;
  policy: Policy;
  match: "any" | "all";
  normalize: boolean;
  terms: Term[];
}

export interface Normalization {
  nfkc: boolean;
  casefold: boolean;
  collapse_whitespace: boolean;
  kana_fold: boolean;
}

export interface Ruleset {
  version: 1;
  normalization: Normalization;
  include_legacy: boolean;
  groups: RuleGroup[];
  price: { min: number | null; max: number | null };
  sources: Source[];
}

export interface RuleVersion {
  id: string;
  version: number;
  search_query: string;
  ruleset: Ruleset;
  restored_from_version_id: string | null;
  created_at: string;
}

export interface DiscordFilter {
  id: number;
  method: string;
  policy: string;
  value: string;
  enabled: boolean;
  matches: number;
}

export interface RulesResponse {
  alert: { id: string; channel_id: string; search_query: string };
  active_version: RuleVersion | null;
  versions: RuleVersion[];
  versions_total: number;
  legacy_filters: DiscordFilter[];
  default_ruleset: Ruleset;
}

export interface ReplayCandidate {
  id: string;
  source: string;
  external_id: string;
  title: string;
  normalized_title: string;
  observation_kind: string;
  origin: string;
  incomplete: boolean;
  observed_at: string;
  last_seen_at: string | null;
  price: number | null;
  url: string | null;
  image_url: string | null;
}

export type Change = "unchanged" | "newly_allowed" | "newly_blocked" | "changed";

export interface ReplayItem {
  candidate: ReplayCandidate;
  original_decision: Decision;
  active_decision: Decision;
  draft_decision: Decision;
  change: Change;
}

export interface ReplaySummary {
  total: number;
  accepted: number;
  filtered: number;
  review: number;
  newly_allowed: number;
  newly_blocked: number;
  changed: number;
  unchanged: number;
  available: number;
  recent: number;
  truncated: boolean;
  budget_exceeded: boolean;
}

export interface ReplayResult {
  items: ReplayItem[];
  summary: ReplaySummary;
  active_version_id: string | null;
}

export interface ImportResult {
  imported: number;
  delivery_import: number;
  item_import: number;
  skipped: number;
  incomplete: number;
  truncated: boolean;
}

/** A Discord post that the rules filter. Message IDs are text: they do not fit in a JavaScript number. */
export interface RemovablePost {
  message_id: string;
  posted_at: string;
  title: string;
  source: string;
  external_id: string;
  price: number | null;
  image_url: string | null;
  url: string | null;
  /** Key of the reason in RemovalPreview.reasons. */
  reason: string;
}

export interface RemovalReason {
  key: string;
  message: string;
  count: number;
}

/** How far back to look, in days; null is all posts. */
export type RemovalDays = 7 | 30 | 90 | null;

export interface RemovalPreview {
  days: RemovalDays;
  posts_in_range: number;
  checked: number;
  partial: boolean;
  removable_total: number;
  limit: number;
  /** This run's posts, newest first; at most `limit`. */
  posts: RemovablePost[];
  reasons: RemovalReason[];
  kept: { allowed: number; review: number; subscribed: number; incomplete: number; unchecked: number; queued: number };
  channel_id: string;
  guild_id: string | null;
  active_version_id: string | null;
  bot_running: boolean;
}

export interface RemovalResult {
  queued: number;
  skipped: number;
  bot_running: boolean;
}

export interface RemovalRun {
  queued_at: string;
  total: number;
  pending: number;
  removed: number;
  failed: number;
  cancelled: number;
}

export interface RemovalStatus {
  run: RemovalRun | null;
  bot_running: boolean;
}

export type GraphRange = "1h" | "6h" | "24h" | "7d";

export interface GraphSeries {
  /** Grafana's legend format with `{{instance}}` removed. May be empty. */
  legend: string;
  labels: Record<string, string>;
  /** One value per entry of `GuildGraphs.times`; null is a gap. */
  values: (number | null)[];
}

export interface GraphColumn {
  key: string;
  title: string;
}

export interface GraphRow {
  labels: Record<string, string>;
  /** null when Prometheus has no number for it. */
  value: number | null;
}

interface GraphPanelBase {
  id: number;
  title: string;
  description: string;
  unit: string;
  decimals: number | null;
  /** "server": only this server's searches. "bot": the whole bot. */
  scope: "server" | "bot";
  error: string | null;
}

export interface TimeseriesPanel extends GraphPanelBase {
  kind: "timeseries";
  style: "bars" | "line";
  stacked: boolean;
  series: GraphSeries[];
}

export interface TablePanel extends GraphPanelBase {
  kind: "table";
  columns: GraphColumn[];
  rows: GraphRow[];
}

export type GraphPanel = TimeseriesPanel | TablePanel;

export interface GraphSection {
  title: string;
  panels: GraphPanel[];
}

export interface GuildGraphs {
  enabled: boolean;
  range: GraphRange;
  ranges: GraphRange[];
  start: number | null;
  end: number | null;
  step: number | null;
  times: number[];
  warning: string | null;
  sections: GraphSection[];
}
