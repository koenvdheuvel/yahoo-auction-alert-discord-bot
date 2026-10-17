// Shapes returned by review.py. IDs are strings because Discord snowflakes exceed 2^53.

export type Source = "yahooauction" | "mercari" | "surugaya";
export type Verdict = "accepted" | "filtered" | "review";
export type Policy = "require" | "exclude" | "review";
export type TermMethod = "contains" | "exact" | "regex";

export interface Session {
  authenticated: boolean;
  expires_in?: number;
  replay_limit?: number;
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
}

export interface AlertsResponse {
  alerts: AlertSummary[];
  totals: { archived_count: number; unassigned_count: number };
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
