import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

export type Tab = "listings" | "rules" | "replay" | "versions";
const TABS: Tab[] = ["listings", "rules", "replay", "versions"];
export type ChannelTab = "searches" | "posts" | "hidden" | "cleanup";
const CHANNEL_TABS: ChannelTab[] = ["searches", "posts", "hidden", "cleanup"];
export type StatusTab = "overview" | "graphs";
const STATUS_TABS: StatusTab[] = ["overview", "graphs"];
/** Pages that belong to a server rather than to a channel or a search, and your own page. */
export type ServerView = "status" | "searches" | "listings";
const SERVER_VIEWS: ServerView[] = ["status", "searches", "listings"];

/**
 * Where the person is. A search wins over a channel, and a channel over the server's pages.
 * `me` is the page of your own 🔔 notifications.
 */
export interface Place {
  /** The Discord server picked in the server list. */
  guildId: string | null;
  channelId: string | null;
  alertId: string | null;
  me: boolean;
  view: ServerView;
  /** The search's tab. */
  tab: Tab;
  channelTab: ChannelTab;
  /** The server status page's tab. */
  statusTab: StatusTab;
}

const digits = (value: string | null) => (value && /^\d+$/.test(value) ? value : null);

function readPlace(): Place {
  const params = new URLSearchParams(window.location.search);
  const alertId = digits(params.get("alert"));
  const channelId = digits(params.get("channel"));
  const tab = params.get("tab");
  const view = params.get("view");
  return {
    guildId: digits(params.get("guild")),
    channelId,
    alertId,
    me: view === "me",
    view: SERVER_VIEWS.includes(view as ServerView) ? view as ServerView : "status",
    tab: TABS.includes(tab as Tab) ? tab as Tab : "listings",
    channelTab: CHANNEL_TABS.includes(tab as ChannelTab) ? tab as ChannelTab : "searches",
    statusTab: STATUS_TABS.includes(tab as StatusTab) ? tab as StatusTab : "overview",
  };
}

function subscribePlace(listener: () => void) {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
}

let snapshot: { search: string; place: Place } | null = null;

function placeSnapshot(): Place {
  if (snapshot?.search !== window.location.search) snapshot = { search: window.location.search, place: readPlace() };
  return snapshot.place;
}

/** The URL for a place. Only what the page needs is in it, so links stay short. */
export function placeUrl(target: Place): string {
  const params = new URLSearchParams();
  if (target.me) {
    params.set("view", "me");
  } else {
    if (target.guildId) params.set("guild", target.guildId);
    if (target.alertId) {
      params.set("alert", target.alertId);
      if (target.tab !== "listings") params.set("tab", target.tab);
    } else if (target.channelId) {
      params.set("channel", target.channelId);
      if (target.channelTab !== "searches") params.set("tab", target.channelTab);
    } else if (target.view !== "status") {
      params.set("view", target.view);
    } else if (target.statusTab !== "overview") {
      params.set("tab", target.statusTab);
    }
  }
  const search = params.toString();
  return `${window.location.pathname}${search ? `?${search}` : ""}`;
}

/** The page lives in the URL, so reload and the back button keep it. */
export function usePlace(): [Place, (next: Partial<Place>) => void] {
  const place = useSyncExternalStore(subscribePlace, placeSnapshot);
  const navigate = useCallback((next: Partial<Place>) => {
    const url = placeUrl({ ...readPlace(), ...next });
    if (url !== `${window.location.pathname}${window.location.search}`) {
      window.history.pushState(null, "", url);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  }, []);
  return [place, navigate];
}

export function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** True when a key press should not trigger a shortcut because the person is typing. */
export function isTyping(event: KeyboardEvent | ReactKeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "reset", "range"].includes(type);
  }
  return target.getAttribute("role") === "combobox";
}
