import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";

import type { Label } from "../../api/types";
import { plural } from "../../lib/format";
import { LABEL_ORDER, LABELS } from "../../lib/vocabulary";
import { LABEL_ICONS } from "./labelIcons";

interface Props {
  count: number;
  busy: boolean;
  onLabel: (label: Label | null) => void;
  onClear: () => void;
}

/** Labels for every selected listing at once. */
export function BulkBar({ count, busy, onLabel, onClear }: Props) {
  return (
    <Box role="toolbar" aria-label="Label the selected listings" sx={{
      position: "sticky", bottom: 16, zIndex: 4, mx: "auto", mt: 2, width: "fit-content", maxWidth: "100%",
      display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1, px: 1.5, py: 1, borderRadius: 1.5,
      bgcolor: "background.paper", border: 1, borderColor: "text.primary", boxShadow: 6,
    }}>
      <Typography variant="body2" sx={{ fontWeight: 650, mr: 1 }}>{plural(count, "listing")} selected</Typography>
      {LABEL_ORDER.map((label) => (
        <Button key={label} size="small" color="inherit" variant="outlined" disabled={busy} startIcon={LABEL_ICONS[label]}
          onClick={() => onLabel(label)} aria-keyshortcuts={LABELS[label].key}>
          {LABELS[label].name}
        </Button>
      ))}
      <Button size="small" color="inherit" disabled={busy} onClick={() => onLabel(null)} aria-keyshortcuts="0">Remove labels</Button>
      <Button size="small" onClick={onClear} aria-keyshortcuts="Escape">Deselect</Button>
    </Box>
  );
}
