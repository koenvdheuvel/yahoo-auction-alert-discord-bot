import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useRemovalPreview } from "../api/hooks";
import type { RemovalDays, Ruleset } from "../api/types";
import { selectedPosts } from "./removal";

export interface PostRemoval {
  days: RemovalDays;
  setDays: (days: RemovalDays) => void;
  /** Reason keys whose posts stay. */
  kept: ReadonlySet<string>;
  toggleReason: (key: string) => void;
  preview: ReturnType<typeof useRemovalPreview>;
  /** Message IDs to remove. */
  selected: string[];
  /** Back to the defaults, so the next opening checks the posts again from scratch. */
  reset: () => void;
}

/** The choices in a "remove the posts these rules filter" preview. Checks only while `enabled`. */
export function usePostRemoval(alertId: string | null, ruleset: Ruleset | undefined, enabled: boolean): PostRemoval {
  const client = useQueryClient();
  const [days, setDays] = useState<RemovalDays>(30);
  const [kept, setKept] = useState<ReadonlySet<string>>(new Set());
  const preview = useRemovalPreview(alertId, days, ruleset, enabled);
  const posts = preview.data?.posts;
  const selected = useMemo(() => (posts ? selectedPosts(posts, kept) : []), [posts, kept]);
  return {
    days,
    setDays: (next) => {
      setDays(next);
      setKept(new Set());
    },
    kept,
    toggleReason: (key) => setKept((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    }),
    preview,
    selected,
    reset: () => {
      setDays(30);
      setKept(new Set());
      client.removeQueries({ queryKey: ["removal-preview"] });
    },
  };
}
