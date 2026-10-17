import Badge from "@mui/material/Badge";
import BottomNavigation from "@mui/material/BottomNavigation";
import BottomNavigationAction from "@mui/material/BottomNavigationAction";
import Box from "@mui/material/Box";
import type { ReactNode } from "react";

import { visuallyHidden } from "../../lib/a11y";
import { useKeyboardOpen } from "../../lib/responsive";

export interface Section<T extends string> {
  value: T;
  label: string;
  icon: ReactNode;
  /** Marks the section with a dot, and says why to screen readers, such as "unpublished changes". */
  note?: string;
}

interface Props<T extends string> {
  /** What the sections belong to, such as "Search sections". */
  label: string;
  sections: Section<T>[];
  value: T;
  onChange: (value: T) => void;
}

/** A page's tabs in a bar at the bottom of the screen on phones, where a thumb reaches them. */
export function SectionBar<T extends string>({ label, sections, value, onChange }: Props<T>) {
  // The on-screen keyboard covers the bottom of the screen; the bar comes back when it closes.
  const keyboard = useKeyboardOpen();
  if (keyboard) return null;
  return (
    <Box component="nav" aria-label={label} sx={{ flex: "none", bgcolor: "surface.sidebar", borderTop: 1, borderColor: "divider",
      pb: "env(safe-area-inset-bottom, 0px)" }}>
      <BottomNavigation showLabels value={value} onChange={(_, next: T) => onChange(next)} sx={{ bgcolor: "transparent" }}>
        {sections.map((section) => (
          <BottomNavigationAction key={section.value} value={section.value} aria-current={section.value === value ? "page" : undefined}
            sx={{ minWidth: 0, color: "text.secondary", "&.Mui-selected": { color: "text.primary" } }}
            icon={section.note
              ? <Badge variant="dot" overlap="circular" sx={{ "& .MuiBadge-dot": { bgcolor: "text.primary" } }}>{section.icon}</Badge>
              : section.icon}
            label={section.note
              ? <>{section.label}<Box component="span" sx={visuallyHidden}> ({section.note})</Box></>
              : section.label} />
        ))}
      </BottomNavigation>
    </Box>
  );
}
