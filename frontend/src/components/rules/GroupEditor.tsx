import ArrowDownward from "@mui/icons-material/ArrowDownward";
import ArrowUpward from "@mui/icons-material/ArrowUpward";
import ContentCopy from "@mui/icons-material/ContentCopy";
import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";

import type { Policy, RuleGroup, TermMethod } from "../../api/types";
import { useCompact, usePhone } from "../../lib/responsive";
import { LIMITS } from "../../lib/ruleset";
import { POLICIES } from "../../lib/vocabulary";
import { MoreActions } from "./MoreActions";
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
  const compact = useCompact();
  const phone = usePhone();
  const set = (changes: Partial<RuleGroup>) => onChange({ ...group, ...changes });
  const name = group.label || `Group ${index + 1}`;

  const nameField = (
    <TextField label="Group name" value={group.label} onChange={(event) => set({ label: event.target.value })}
      sx={{ flex: 1, maxWidth: compact ? undefined : 300 }} slotProps={{ htmlInput: { maxLength: LIMITS.label } }}
      error={!group.label.trim()} helperText={group.label.trim() ? undefined : "Give the group a name"} />
  );
  // On narrow screens the role and the toggle split the row evenly, but neither gets narrower than its text.
  const share = { flex: "1 1 0", minWidth: "min-content" } as const;
  const roleField = (
    <TextField select label="Role" value={group.policy} onChange={(event) => set({ policy: event.target.value as Policy })}
      sx={compact ? share : { minWidth: 176 }}>
      {(Object.keys(POLICIES) as Policy[]).map((policy) => <MenuItem key={policy} value={policy}>{POLICIES[policy].name}</MenuItem>)}
    </TextField>
  );
  const matchToggle = (
    <ToggleButtonGroup exclusive size="small" fullWidth={compact} value={group.match} aria-label={`How the terms of ${name} combine`}
      onChange={(_, match: RuleGroup["match"] | null) => match && set({ match })}
      sx={compact ? { ...share, "& .MuiToggleButton-root": { minWidth: 56 } } : undefined}>
      {/* "Any term" and "All terms" are too wide to share a phone's row with the role, so there they read "Any" and "All". */}
      <ToggleButton value="any" aria-label={phone ? "Any term" : undefined}>{phone ? "Any" : "Any term"}</ToggleButton>
      <ToggleButton value="all" aria-label={phone ? "All terms" : undefined}>{phone ? "All" : "All terms"}</ToggleButton>
    </ToggleButtonGroup>
  );
  const more = (
    <MoreActions label={`More actions for ${name}`} title={name} actions={[
      { label: "Move up", icon: <ArrowUpward fontSize="small" />, disabled: index === 0, onSelect: () => onMove(-1) },
      { label: "Move down", icon: <ArrowDownward fontSize="small" />, disabled: index === count - 1, onSelect: () => onMove(1) },
      { label: "Duplicate", icon: <ContentCopy fontSize="small" />, disabled: count >= LIMITS.groups, onSelect: onDuplicate },
      { label: "Delete group", icon: <DeleteOutlined fontSize="small" />, onSelect: onRemove },
    ]} />
  );

  return (
    <Box component="section" aria-label={name} sx={{
      bgcolor: "background.paper", border: 1, borderColor: error ? "error.main" : "divider", borderRadius: 1,
      borderLeft: 4, borderLeftColor: RULE_COLOR[group.policy], p: 2, display: "grid", gap: 1.5,
    }}>
      {compact ? (
        // Two rows on narrow screens: the name with its ⋮, then the role and how the terms combine.
        // Those two share the second row, and wrap onto their own rows when it is too narrow for both.
        <Box sx={{ display: "grid", gap: 1.25 }}>
          <Box sx={{ display: "flex", gap: 1, alignItems: "flex-start" }}>{nameField}{more}</Box>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.25 }}>{roleField}{matchToggle}</Box>
        </Box>
      ) : (
        <Stack direction="row" spacing={1.25} sx={{ alignItems: "center" }}>
          {nameField}{roleField}{matchToggle}
          <Box sx={{ flex: 1 }} />
          {more}
        </Stack>
      )}
      <Typography variant="body2" color="textSecondary">{POLICIES[group.policy].description} {explain(group)}</Typography>
      <TermEditor terms={group.terms} onChange={(terms) => set({ terms })} cannotAdd={cannotAdd}
        errorTerm={error?.term} groupLabel={name} />
      {!group.terms.length && (
        <Typography variant="body2" color="warning">Add at least one term; a group without terms cannot be published.</Typography>
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
