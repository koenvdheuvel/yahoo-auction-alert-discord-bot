import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";

// The access-key login has no personal identity; it uses its own browser-local read history.
export const SearchReadOwner = createContext<string | null>(null);
const PREFIX = "dashboard:read:";
const MAX_ID = 2n ** 63n - 1n;
const listeners = new Set<() => void>();
const volatile = new Map<string, string>();

/** A positive signed 64-bit database ID, the only kind the server accepts; a corrupted stored cursor is none. */
export function isIdentifier(value: string | null | undefined): value is string {
  return typeof value === "string" && /^[1-9][0-9]{0,18}$/.test(value) && BigInt(value) <= MAX_ID;
}

const cursorKey = (owner: string | null, alertId: string | null) => (owner && alertId ? `${PREFIX}${owner}:${alertId}` : null);

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
  return isIdentifier(value) ? value : null;
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

/** One read cursor per user and search; `readThrough` is null until the person has read any of its listings. */
export function useSearchRead(alertId: string | null) {
  const owner = useContext(SearchReadOwner);
  const key = cursorKey(owner, alertId);
  const readThrough = useSyncExternalStore(subscribe, () => readPosition(key));
  const markRead = useCallback((candidateId: string) => {
    if (!key || !isIdentifier(candidateId)) return;
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
  return { readThrough, markRead };
}

/** The read cursors of a whole list of searches behind one subscription, for whoever counts them together. */
export function useReadPositions(alertIds: readonly string[]): ReadonlyMap<string, string | null> {
  const owner = useContext(SearchReadOwner);
  // A string is the same value until a cursor really moves, which is what the store needs from a snapshot.
  const snapshot = useSyncExternalStore(subscribe, () => alertIds.map((id) => readPosition(cursorKey(owner, id)) ?? "").join(","));
  return useMemo(() => {
    const cursors = snapshot.split(",");
    return new Map(alertIds.map((id, index) => [id, cursors[index] || null]));
  }, [alertIds, snapshot]);
}
