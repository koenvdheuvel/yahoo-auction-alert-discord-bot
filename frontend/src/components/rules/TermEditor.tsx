import Add from "@mui/icons-material/Add";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useId, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from "react";

import type { Term, TermMethod } from "../../api/types";
import { usePhone } from "../../lib/responsive";
import { termLimit } from "../../lib/ruleset";
import { METHODS } from "../../lib/vocabulary";
import { mono } from "../../theme";
import { SheetDialog } from "../common/Sheet";

interface Props {
  terms: Term[];
  onChange: (terms: Term[]) => void;
  /** Why no more terms fit, counting terms already taken from the same paste, or null. */
  cannotAdd: (method: TermMethod, added: { terms: number; regex: number }) => string | null;
  errorTerm: number | undefined;
  groupLabel: string;
}

const METHOD_NAMES = Object.keys(METHODS) as TermMethod[];

// On touch screens a chip is 44 pixels tall, and its delete icon gets a square of the chip's height around it,
// so a finger can pick editing or deleting.
const touchChip = {
  "@media (pointer: coarse)": {
    minHeight: 44,
    "& .MuiChip-deleteIcon": { boxSizing: "content-box", p: "11px", ml: -1, mr: 0 },
  },
} as const;

function MethodSelect({ value, onChange, label }: { value: TermMethod; onChange: (method: TermMethod) => void; label: string }) {
  return (
    <TextField select value={value} onChange={(event) => onChange(event.target.value as TermMethod)} sx={{ minWidth: 132 }}
      label={label}>
      {METHOD_NAMES.map((method) => <MenuItem key={method} value={method}>{METHODS[method].name}</MenuItem>)}
    </TextField>
  );
}

export function TermEditor({ terms, onChange, cannotAdd, errorTerm, groupLabel }: Props) {
  const phone = usePhone();
  const titleId = useId();
  const [text, setText] = useState("");
  const [method, setMethod] = useState<TermMethod>("contains");
  const [problem, setProblem] = useState<string | null>(null);
  // The last term opened stays here after closing, so the form does not empty while it slides away.
  const [editing, setEditing] = useState<{ index: number; anchor: HTMLElement; term: Term } | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const add = (values: string[]) => {
    const fresh = values.map((value) => value.trim()).filter(Boolean)
      .filter((value) => !terms.some((term) => term.method === method && term.value === value));
    if (!fresh.length) return;
    const next = [...terms];
    for (const value of fresh) {
      const count = next.length - terms.length;
      const blocked = cannotAdd(method, { terms: count, regex: method === "regex" ? count : 0 });
      if (blocked) {
        setProblem(blocked);
        break;
      }
      if (value.length > termLimit(method)) {
        setProblem(`A ${METHODS[method].name.toLowerCase()} term holds at most ${termLimit(method)} characters.`);
        continue;
      }
      next.push({ method, value });
    }
    if (next.length !== terms.length) onChange(next);
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      add([text]);
    }
  };
  // Pasting several lines adds one term per line, for alias lists.
  const onPaste = (event: ClipboardEvent) => {
    const pasted = event.clipboardData.getData("text");
    if (!pasted.includes("\n")) return;
    event.preventDefault();
    add(pasted.split(/\r?\n/));
  };

  const closeEdit = () => setEditOpen(false);
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!editing) return;
    const value = editing.term.value.trim();
    if (value) onChange(terms.map((term, at) => (at === editing.index ? { ...editing.term, value } : term)));
    closeEdit();
  };
  const removeEdited = () => {
    if (editing) onChange(terms.filter((_, at) => at !== editing.index));
    closeEdit();
  };
  const editMethod = editing && (
    <MethodSelect value={editing.term.method} label="Match"
      onChange={(next) => setEditing({ ...editing, term: { ...editing.term, method: next } })} />
  );
  const editHint = editing && (
    <Typography variant="caption" color="textSecondary">{METHODS[editing.term.method].description}</Typography>
  );
  // On phones the keyboard would cover the sheet's buttons, so the field waits for a tap.
  const editValue = editing && (
    <TextField label="Term" value={editing.term.value} autoFocus={!phone} fullWidth
      onChange={(event) => setEditing({ ...editing, term: { ...editing.term, value: event.target.value } })}
      slotProps={{ htmlInput: { maxLength: termLimit(editing.term.method), spellCheck: false } }} />
  );
  const canSave = Boolean(editing?.term.value.trim());

  const field = (
    <TextField
      value={text}
      onChange={(event) => { setText(event.target.value); setProblem(null); }}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      label="Add a term"
      placeholder={terms.length ? "Another spelling or alias" : "A word or phrase from the title"}
      error={problem !== null}
      helperText={problem ?? undefined}
      sx={{ flex: 1, maxWidth: phone ? undefined : 420 }}
      slotProps={{ htmlInput: { maxLength: termLimit(method), spellCheck: false, ...(method === "regex" && { style: { fontFamily: mono } }) } }}
    />
  );

  return (
    <Box>
      <Box component="ul" aria-label={`Terms in ${groupLabel}`} sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, p: 0, m: 0, mb: 1.25,
        listStyle: "none", "&:empty": { display: "none" }, "@media (pointer: coarse)": { gap: 1 } }}>
        {terms.map((term, index) => (
          <li key={`${term.method}-${term.value}-${index}`}>
            <Chip
              variant="outlined"
              color={errorTerm === index ? "error" : "default"}
              onClick={(event) => {
                setEditing({ index, anchor: event.currentTarget, term });
                setEditOpen(true);
              }}
              onDelete={() => onChange(terms.filter((_, at) => at !== index))}
              aria-label={`${METHODS[term.method].name}: ${term.value}. Select to edit.`}
              label={
                <Box component="span" sx={{ display: "inline-flex", gap: 0.75, alignItems: "baseline" }}>
                  {term.method !== "contains" && (
                    <Box component="span" sx={{ color: "text.secondary", fontSize: "0.6875rem", fontWeight: 650 }}>
                      {METHODS[term.method].name}
                    </Box>
                  )}
                  <Box component="span" sx={term.method === "regex" ? { fontFamily: mono, fontSize: "0.75rem" } : undefined}>
                    {term.value}
                  </Box>
                </Box>
              }
              sx={{ maxWidth: "100%", height: "auto", minHeight: 26, "& .MuiChip-label": { whiteSpace: "normal", overflowWrap: "anywhere", py: 0.25 },
                ...touchChip }}
              // Phone browsers move a tap to the nearest thing that takes clicks. A click handler on the label
              // keeps a tap on the label there instead of moving it onto the delete icon; the chip handles the click.
              slotProps={{ label: { onClick: () => undefined } }}
            />
          </li>
        ))}
      </Box>
      {phone ? (
        // The field with a square Add button on its right, and how the term matches under it.
        <Box sx={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 1, alignItems: "start" }}>
          {field}
          <Box sx={{ gridRow: 2, justifySelf: "start" }}><MethodSelect value={method} onChange={setMethod} label="Match" /></Box>
          <Button variant="outlined" color="inherit" aria-label="Add" onClick={() => add([text])} disabled={!text.trim()}
            sx={{ gridRow: 1, gridColumn: 2, minWidth: 44, width: 44, height: 40, px: 0 }}>
            <Add />
          </Button>
        </Box>
      ) : (
        <Stack direction="row" spacing={1} sx={{ alignItems: "flex-start" }}>
          {field}
          <MethodSelect value={method} onChange={setMethod} label="Match" />
          <Button variant="outlined" color="inherit" startIcon={<Add />} onClick={() => add([text])} disabled={!text.trim()}
            sx={{ height: 40 }}>
            Add
          </Button>
        </Stack>
      )}
      {phone ? (
        <SheetDialog open={editOpen} onClose={closeEdit} maxWidth="xs" aria-labelledby={titleId}>
          <Box component="form" onSubmit={save} sx={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <DialogTitle id={titleId}>Edit term</DialogTitle>
            {/* The top padding keeps the label of the first field from being cut off. */}
            <DialogContent sx={{ display: "grid", gap: 1.5, pt: "8px !important" }}>
              {editMethod}
              {editHint}
              {editValue}
            </DialogContent>
            <DialogActions>
              <Button color="inherit" onClick={removeEdited}>Remove</Button>
              <Button type="submit" variant="contained" disabled={!canSave}>Save</Button>
            </DialogActions>
          </Box>
        </SheetDialog>
      ) : (
        <Popover open={editOpen} anchorEl={editing?.anchor} onClose={closeEdit}
          anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
          slotProps={{ paper: { sx: { p: 2, width: 360, border: 1, borderColor: "divider" } } }}>
          {editing && (
            <Stack component="form" spacing={1.5} onSubmit={save}>
              <Typography variant="subtitle2">Edit term</Typography>
              {editMethod}
              {editHint}
              {editValue}
              <Stack direction="row" spacing={1} sx={{ justifyContent: "flex-end" }}>
                <Button color="inherit" onClick={removeEdited}>Remove</Button>
                <Button type="submit" variant="contained" disabled={!canSave}>Save</Button>
              </Stack>
            </Stack>
          )}
        </Popover>
      )}
    </Box>
  );
}
