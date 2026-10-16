import { useCallback, useMemo } from "react";

import type { RulesResponse, RuleVersion, Ruleset } from "../api/types";
import { clearDraft, saveDraft, useStoredDraft } from "./drafts";
import { canonical, defaultRuleset, sameRuleset } from "./ruleset";

export interface Draft {
  /** False while the alert's published rules are loading; the draft is not editable yet. */
  ready: boolean;
  ruleset: Ruleset;
  /** The canonical JSON of the draft, for comparing and for validation. */
  serialized: string;
  published: RuleVersion | null;
  publishedRuleset: Ruleset;
  /** The published version the draft started from; publishing checks it is still current. */
  baseVersionId: string | null;
  /** The draft differs from the published rules. */
  edited: boolean;
  /** Someone published another version after this draft started. */
  outdated: boolean;
  update: (next: Ruleset) => void;
  discard: () => void;
  /** Keep the draft's rules but start from the version that is published now. */
  rebase: () => void;
}

/** The working draft for an alert, or for "scratch" when no alert is selected. */
export function useDraft(alertId: string | null, rules: RulesResponse | undefined): Draft {
  const key = alertId ?? "scratch";
  const stored = useStoredDraft(key);
  const ready = alertId === null || rules !== undefined;
  const published = rules?.active_version ?? null;
  const publishedRuleset = useMemo(
    () => published?.ruleset ?? rules?.default_ruleset ?? defaultRuleset(),
    [published, rules?.default_ruleset],
  );
  const publishedId = published?.id ?? null;
  const ruleset = stored?.ruleset ?? publishedRuleset;
  const baseVersionId = stored ? stored.baseVersionId : publishedId;
  const serialized = useMemo(() => JSON.stringify(canonical(ruleset)), [ruleset]);

  const update = useCallback((next: Ruleset) => {
    if (!ready) return;
    saveDraft(key, { ruleset: next, baseVersionId: stored ? stored.baseVersionId : publishedId });
  }, [key, ready, stored, publishedId]);
  const discard = useCallback(() => clearDraft(key), [key]);
  const rebase = useCallback(() => {
    if (stored) saveDraft(key, { ruleset: stored.ruleset, baseVersionId: publishedId });
  }, [key, stored, publishedId]);

  return {
    ready,
    ruleset,
    serialized,
    published,
    publishedRuleset,
    baseVersionId,
    edited: stored !== null && !sameRuleset(stored.ruleset, publishedRuleset),
    outdated: ready && alertId !== null && stored !== null && stored.baseVersionId !== publishedId,
    update,
    discard,
    rebase,
  };
}
