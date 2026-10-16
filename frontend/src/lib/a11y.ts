/**
 * Hides content visually while screen readers still read it. Sizes are strings because `sx` reads
 * `width: 1` as 100% and `margin: -1` as one spacing unit.
 */
export const visuallyHidden = {
  position: "absolute", width: "1px", height: "1px", padding: 0, margin: "-1px", overflow: "hidden",
  clip: "rect(0 0 0 0)", whiteSpace: "nowrap", border: 0,
} as const;
