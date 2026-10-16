import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

export type Tab = "listings" | "rules" | "replay" | "versions";
const TABS: Tab[] = ["listings", "rules", "replay", "versions"];

export interface Place {
  alertId: string | null;
  /** The Discord server picked in the side panel, for people who manage more than one. */
  guildId: string | null;
  tab: Tab;
}

function readPlace(): Place {
  const params = new URLSearchParams(window.location.search);
  const alert = params.get("alert");
  const guild = params.get("guild");
  const tab = params.get("tab") as Tab | null;
  return {
    alertId: alert && /^\d+$/.test(alert) ? alert : null,
    guildId: guild && /^\d+$/.test(guild) ? guild : null,
    tab: tab && TABS.includes(tab) ? tab : "listings",
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

/** The selected alert and tab live in the URL, so reload and the back button keep them. */
export function usePlace(): [Place, (next: Partial<Place>) => void] {
  const place = useSyncExternalStore(subscribePlace, placeSnapshot);
  const navigate = useCallback((next: Partial<Place>) => {
    const target = { ...readPlace(), ...next };
    const params = new URLSearchParams();
    if (target.alertId) params.set("alert", target.alertId);
    if (target.guildId) params.set("guild", target.guildId);
    if (target.tab !== "listings") params.set("tab", target.tab);
    const search = params.toString();
    const url = `${window.location.pathname}${search ? `?${search}` : ""}`;
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
