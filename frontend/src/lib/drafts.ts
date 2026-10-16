import { useMemo, useSyncExternalStore } from "react";

import type { Ruleset } from "../api/types";

// Drafts survive reloads and expired sessions. Signing out removes them. The access key is
// never stored in the browser.
const PREFIX = "filter-lab:draft:";
const listeners = new Set<() => void>();

export interface StoredDraft {
  ruleset: Ruleset;
  /** The published version the draft started from; null when nothing was published. */
  baseVersionId: string | null;
  savedAt: string;
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Another tab editing the same draft.
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key.startsWith(PREFIX)) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The stored draft for an alert ("scratch" when no alert is selected), or null. */
export function useStoredDraft(key: string): StoredDraft | null {
  const raw = useSyncExternalStore(subscribe, () => storage()?.getItem(PREFIX + key) ?? null);
  return useMemo(() => {
    if (!raw) return null;
    try {
      const value = JSON.parse(raw) as StoredDraft;
      return value && typeof value === "object" && value.ruleset ? value : null;
    } catch {
      return null;
    }
  }, [raw]);
}

export function saveDraft(key: string, draft: Omit<StoredDraft, "savedAt">) {
  try {
    storage()?.setItem(PREFIX + key, JSON.stringify({ ...draft, savedAt: new Date().toISOString() }));
  } catch {
    // Storage full or blocked: the draft still lives in memory until the page reloads.
  }
  emit();
}

export function clearDraft(key: string) {
  storage()?.removeItem(PREFIX + key);
  emit();
}

export function clearAllDrafts() {
  const store = storage();
  if (!store) return;
  for (const key of Object.keys(store)) if (key.startsWith(PREFIX)) store.removeItem(key);
  emit();
}

export function countDrafts(): number {
  const store = storage();
  return store ? Object.keys(store).filter((key) => key.startsWith(PREFIX)).length : 0;
}
