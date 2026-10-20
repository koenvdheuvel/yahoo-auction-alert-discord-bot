import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

// The access-key login has no personal identity; it uses its own browser-local read history.
export const SearchReadOwner = createContext<string | null>(null);
const PREFIX = "dashboard:read:";
const listeners = new Set<() => void>();
const volatile = new Map<string, string>();
const identifier = (value: string | null): value is string => value !== null && /^[1-9][0-9]{0,18}$/.test(value);

function readPosition(key: string | null): string | null {
  if (!key) return null;
  let value = volatile.get(key) ?? null;
  if (value === null) {
    try {
      value = window.localStorage.getItem(key);
    } catch {
      // Reading is blocked too: the position stays in memory until the page reloads.
    }
  }
  return identifier(value) ? value : null;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null) volatile.clear();
    else if (event.key.startsWith(PREFIX)) volatile.delete(event.key);
    else return;
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** One read cursor per user and search. A fresh check of an unchanged listing is not unread. */
export function useSearchRead(alertId: string | null, latestCandidateId: string | null = null) {
  const owner = useContext(SearchReadOwner);
  const key = owner && alertId ? `${PREFIX}${owner}:${alertId}` : null;
  const readThrough = useSyncExternalStore(subscribe, () => readPosition(key));
  const markRead = useCallback((candidateId: string) => {
    if (!key || !identifier(candidateId)) return;
    const previous = readPosition(key);
    // A stale page or another tab must not move the read position backwards.
    if (previous && BigInt(previous) >= BigInt(candidateId)) return;
    try {
      window.localStorage.setItem(key, candidateId);
      volatile.delete(key);
    } catch {
      // Full or blocked storage: still track reads until the page reloads.
      volatile.set(key, candidateId);
    }
    listeners.forEach((listener) => listener());
  }, [key]);
  const unread = Boolean(key && latestCandidateId && (!readThrough || BigInt(latestCandidateId) > BigInt(readThrough)));
  return { unread, markRead };
}
