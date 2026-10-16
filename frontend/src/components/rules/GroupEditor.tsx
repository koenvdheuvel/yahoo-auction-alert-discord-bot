import ArrowDownward from "@mui/icons-material/ArrowDownward";
import ArrowUpward from "@mui/icons-material/ArrowUpward";
import ContentCopy from "@mui/icons-material/ContentCopy";
import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import MoreVert from "@mui/icons-material/MoreVert";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import type { Policy, RuleGroup, TermMethod } from "../../api/types";
import { LIMITS } from "../../lib/ruleset";
import { POLICIES } from "../../lib/vocabulary";
import { TermEditor } from "./TermEditor";

// Must-match groups are printed in ink, exclusions in the filtered grey, holds in the review amber.
const RULE_COLOR: Record<Policy, string> = { require: "text.primary", exclude: "text.secondary", review: "warning.main" };

function explain(group: RuleGroup): string {
  const all = group.match === "all";
  if (group.policy === "require") return all ? "Every term must be in the title." : "At least one term must be in the title.";
  if (group.policy === "exclude") return all ? "Filtered when every term is in the title." : "Filtered when any term is in the title.";
  return all ? "Held for review when every term is in the title." : "Held for review when any term is in the title.";
}

interface Props {
  group: RuleGroup;
  index: number;
  count: number;
  error: { message: string; term: number | undefined } | null;
  onChange: (group: RuleGroup) => void;
  onMove: (offset: -1 | 1) => void;
  onDuplicate: () => void;
  onRemove: () => void;
  cannotAdd: (method: TermMethod, added: { terms: number; regex: number }) => string | null;
}

export function GroupEditor({ group, index, count, error, onChange, onMove, onDuplicate, onRemove, cannotAdd }: Props) {
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  const set = (changes: Partial<RuleGroup>) => onChange({ ...group, ...changes });
  const name = group.label || `Group ${index + 1}`;
  return (
    <Box component="section" aria-label={name} sx={{
      bgcolor: "background.paper", border: 1, borderColor: error ? "error.main" : "divider", borderRadius: 1,
      borderLeft: 4, borderLeftColor: RULE_COLOR[group.policy], p: 2, display: "grid", gap: 1.5,
    }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} sx={{ alignItems: { md: "center" } }}>
        <TextField label="Group name" value={group.label} onChange={(event) => set({ label: event.target.value })}
          sx={{ flex: 1, maxWidth: { md: 300 } }} slotProps={{ htmlInput: { maxLength: LIMITS.label } }}
          error={!group.label.trim()} helperText={group.label.trim() ? undefined : "Give the group a name"} />
        <TextField select label="Role" value={group.policy} onChange={(event) => set({ policy: event.target.value as Policy })}
          sx={{ minWidth: 176 }}>
          {(Object.keys(POLICIES) as Policy[]).map((policy) => <MenuItem key={policy} value={policy}>{POLICIES[policy].name}</MenuItem>)}
        </TextField>
        <ToggleButtonGroup exclusive size="small" value={group.match} aria-label={`How the terms of ${name} combine`}
          onChange={(_, match: RuleGroup["match"] | null) => match && set({ match })}>
          <ToggleButton value="any">Any term</ToggleButton>
          <ToggleButton value="all">All terms</ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flex: 1, display: { xs: "none", md: "block" } }} />
        <IconButton aria-label={`More actions for ${name}`} onClick={(event) => setMenu(event.currentTarget)}
          sx={{ alignSelf: { xs: "flex-end", md: "center" } }}>
          <MoreVert />
        </IconButton>
        <Menu anchorEl={menu} open={menu !== null} onClose={() => setMenu(null)}>
          <MenuItem disabled={index === 0} onClick={() => { setMenu(null); onMove(-1); }}>
            <ListItemIcon><ArrowUpward fontSize="small" /></ListItemIcon><ListItemText>Move up</ListItemText>
          </MenuItem>
          <MenuItem disabled={index === count - 1} onClick={() => { setMenu(null); onMove(1); }}>
            <ListItemIcon><ArrowDownward fontSize="small" /></ListItemIcon><ListItemText>Move down</ListItemText>
          </MenuItem>
          <MenuItem disabled={count >= LIMITS.groups} onClick={() => { setMenu(null); onDuplicate(); }}>
            <ListItemIcon><ContentCopy fontSize="small" /></ListItemIcon><ListItemText>Duplicate</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => { setMenu(null); onRemove(); }}>
            <ListItemIcon><DeleteOutlined fontSize="small" /></ListItemIcon><ListItemText>Delete group</ListItemText>
          </MenuItem>
        </Menu>
      </Stack>
      <Typography variant="body2" color="text.secondary">{POLICIES[group.policy].description} {explain(group)}</Typography>
      <TermEditor terms={group.terms} onChange={(terms) => set({ terms })} cannotAdd={cannotAdd}
        errorTerm={error?.term} groupLabel={name} />
      {!group.terms.length && (
        <Typography variant="body2" color="warning.main">Add at least one term; a group without terms cannot be published.</Typography>
      )}
      <FormControlLabel
        control={<Switch size="small" checked={group.normalize} onChange={(event) => set({ normalize: event.target.checked })} />}
        label="Compare with the normalized title"
        slotProps={{ typography: { variant: "body2" } }}
        sx={{ justifySelf: "start" }}
      />
      {error && <Alert severity="error" variant="outlined">{error.message}</Alert>}
    </Box>
  );
}
