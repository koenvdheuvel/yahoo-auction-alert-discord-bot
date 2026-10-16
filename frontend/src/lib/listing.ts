import type { Candidate } from "../api/types";

/** The compared title is worth showing only when normalization did more than lowercase and tidy spaces. */
export function surprisingNormalization(candidate: Candidate): string | null {
  const loose = candidate.title.normalize("NFKC").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  return candidate.normalized_title && candidate.normalized_title !== loose ? candidate.normalized_title : null;
}

export function listingTitle(candidate: Pick<Candidate, "title" | "payload">): string {
  return candidate.title || candidate.payload.title || "Untitled listing";
}
