import { keyframes } from "@emotion/react";
import Box from "@mui/material/Box";

import type { Label } from "../../api/types";
import { LABELS, type MarkShape } from "../../lib/vocabulary";

// Strokes a person makes with a china marker on a contact sheet: loop the keepers,
// cross out the rejects, and put a question mark on the ones to look at again.
const STROKES: Record<MarkShape, string[]> = {
  circle: ["M30 7C17 4 6 13 6 25s11 18 22 16c11-2 16-12 13-23-2-7-9-11-19-9"],
  cross: ["M11 10c8 8 17 18 27 29", "M37 9c-9 10-18 20-28 29"],
  question: ["M15 16c0-7 7-10 12-9 6 1 9 6 7 11-2 5-9 6-10 12v3", "M24 40.2l.3.6"],
};

const draw = keyframes`
  from { stroke-dashoffset: 1; }
  to { stroke-dashoffset: 0; }
`;

interface Props {
  label: Label;
  size?: number;
  /** Draw the stroke in, for a label the person just set. */
  animate?: boolean;
}

/** The label's mark. Decorative: the label's name is always shown as text next to it. */
export function LabelMark({ label, size = 44, animate = false }: Props) {
  const strokes = STROKES[LABELS[label].mark];
  return (
    <Box
      component="svg"
      viewBox="0 0 48 48"
      aria-hidden="true"
      sx={{ width: size, height: size, display: "block", overflow: "visible", transform: "rotate(-4deg)" }}
    >
      {strokes.map((path) => (
        <Box component="path" key={`halo-${path}`} d={path} sx={{
          fill: "none", stroke: "var(--mui-palette-background-paper)", strokeWidth: 7, opacity: 0.85,
          strokeLinecap: "round", strokeLinejoin: "round",
        }} />
      ))}
      {strokes.map((path, index) => (
        <Box
          component="path"
          key={path}
          d={path}
          pathLength={1}
          sx={{
            fill: "none",
            stroke: "var(--mui-palette-secondary-main)",
            strokeWidth: 3.6,
            strokeLinecap: "round",
            strokeLinejoin: "round",
            strokeDasharray: 1,
            strokeDashoffset: 0,
            ...(animate && {
              strokeDashoffset: 1,
              animation: `${draw} 260ms ease-out ${index * 140}ms forwards`,
            }),
          }}
        />
      ))}
    </Box>
  );
}
