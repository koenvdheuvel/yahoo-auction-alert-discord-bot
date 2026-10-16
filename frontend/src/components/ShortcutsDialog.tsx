import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Typography from "@mui/material/Typography";

import { LABEL_ORDER, LABELS } from "../lib/vocabulary";

const GROUPS: [string, [string[], string][]][] = [
  ["Listings", [
    [["j", "→"], "Next listing"],
    [["k", "←"], "Previous listing"],
    [["↓", "↑"], "Next or previous row of photos"],
    ...LABEL_ORDER.map((label): [string[], string] => [[LABELS[label].key], `Label ${LABELS[label].name}; again to remove`]),
    [["0", "Backspace"], "Remove the label"],
    [["x", "Space"], "Select or deselect; Shift selects a range"],
    [["Ctrl A", "⌘ A"], "Select every loaded listing"],
    [["Esc"], "Deselect all"],
    [["Enter"], "Show details"],
    [["o"], "Open the listing on its marketplace"],
    [["t"], "Test the listing's title with the draft"],
    [["/"], "Search listings"],
  ]],
  ["Everywhere", [
    [["t"], "Test a title"],
    [["?"], "Show these keys"],
  ]],
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" aria-labelledby="shortcuts-title">
      <DialogTitle id="shortcuts-title">Keyboard shortcuts</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2.5 }}>
        {GROUPS.map(([group, rows]) => (
          <Box key={group}>
            <Typography variant="subtitle2" component="h3" sx={{ mb: 1 }}>{group}</Typography>
            {/* A fixed key column lines the descriptions up across both groups. */}
            <Box component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: "7.5rem 1fr", columnGap: 2, rowGap: 0.75 }}>
              {rows.map(([keys, action]) => (
                <Box key={`${group}-${action}`} sx={{ display: "contents" }}>
                  <Box component="dt" sx={{ display: "flex", gap: 0.5 }}>
                    {keys.map((key) => (
                      <Box component="kbd" key={key} sx={{ px: 0.75, minWidth: 24, textAlign: "center", border: 1, borderColor: "divider",
                        borderRadius: 0.75, fontFamily: "inherit", fontSize: "0.8125rem", bgcolor: "action.hover" }}>{key}</Box>
                    ))}
                  </Box>
                  <Typography component="dd" variant="body2" sx={{ m: 0 }}>{action}</Typography>
                </Box>
              ))}
            </Box>
          </Box>
        ))}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}
