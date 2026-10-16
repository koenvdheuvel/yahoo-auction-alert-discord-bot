/** Browser storage keys used to start with "filter-lab:". This moves them to "dashboard:" once. */
const OLD = "filter-lab:";
const NEW = "dashboard:";

/** Moves saved drafts and settings to their new keys. A value already under the new key wins. */
export function moveOldKeys() {
  let store: Storage;
  try {
    store = window.localStorage;
  } catch {
    return;
  }
  for (const key of Object.keys(store)) {
    if (!key.startsWith(OLD)) continue;
    const target = NEW + key.slice(OLD.length);
    const value = store.getItem(key);
    try {
      if (value !== null && store.getItem(target) === null) store.setItem(target, value);
      store.removeItem(key);
    } catch {
      // Storage full or blocked: leave the old key for the next page load.
    }
  }
}
