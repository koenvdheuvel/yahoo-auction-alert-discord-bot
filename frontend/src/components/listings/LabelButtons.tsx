import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";

import type { Label } from "../../api/types";
import { LABEL_ORDER, LABELS } from "../../lib/vocabulary";
import { LABEL_ICONS } from "./labelIcons";

interface Props {
  value: Label | null;
  onChange: (label: Label | null) => void;
  /** What is being labeled, for screen readers. */
  subject: string;
  disabled?: boolean;
  tabIndex?: number;
}

/** Five toggles; choosing the current label again removes it. Keys 1 to 5 do the same. */
export function LabelButtons({ value, onChange, subject, disabled = false, tabIndex }: Props) {
  return (
    <ToggleButtonGroup exclusive size="small" value={value} disabled={disabled} aria-label={`Label for ${subject}`}
      onChange={(_, next: Label | null) => onChange(next)}>
      {LABEL_ORDER.map((label) => (
        <Tooltip key={label} title={`${LABELS[label].name} (${LABELS[label].key})`} disableInteractive>
          <ToggleButton value={label} aria-label={LABELS[label].name} tabIndex={tabIndex} sx={{
            px: 0.75, py: 0.5, fontSize: "1.05rem", color: "text.secondary",
            "&.Mui-selected, &.Mui-selected:hover": {
              color: "secondary.main", bgcolor: "rgba(var(--mui-palette-secondary-mainChannel) / 0.1)",
            },
          }}>
            {LABEL_ICONS[label]}
          </ToggleButton>
        </Tooltip>
      ))}
    </ToggleButtonGroup>
  );
}
