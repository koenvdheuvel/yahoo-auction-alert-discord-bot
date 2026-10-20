import Add from "@mui/icons-material/Add";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useState, type ClipboardEvent, type KeyboardEvent } from "react";

import type { Term, TermMethod } from "../../api/types";
import { termLimit } from "../../lib/ruleset";
import { METHODS } from "../../lib/vocabulary";
import { mono } from "../../theme";

interface Props {
  terms: Term[];
  onChange: (terms: Term[]) => void;
  /** Why no more terms fit, counting terms already taken from the same paste, or null. */
  cannotAdd: (method: TermMethod, added: { terms: number; regex: number }) => string | null;
  errorTerm: number | undefined;
  groupLabel: string;
}

const METHOD_NAMES = Object.keys(METHODS) as TermMethod[];

function MethodSelect({ value, onChange, label }: { value: TermMethod; onChange: (method: TermMethod) => void; label: string }) {
  return (
    <TextField select value={value} onChange={(event) => onChange(event.target.value as TermMethod)} sx={{ minWidth: 132 }}
      label={label}>
      {METHOD_NAMES.map((method) => <MenuItem key={method} value={method}>{METHODS[method].name}</MenuItem>)}
    </TextField>
  );
}

export function TermEditor({ terms, onChange, cannotAdd, errorTerm, groupLabel }: Props) {
  const [text, setText] = useState("");
  const [method, setMethod] = useState<TermMethod>("contains");
  const [problem, setProblem] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ index: number; anchor: HTMLElement; term: Term } | null>(null);

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

  return (
    <Box>
      <Box component="ul" aria-label={`Terms in ${groupLabel}`} sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, p: 0, m: 0, mb: 1.25,
        listStyle: "none", "&:empty": { display: "none" } }}>
        {terms.map((term, index) => (
          <li key={`${term.method}-${term.value}-${index}`}>
            <Chip
              variant="outlined"
              color={errorTerm === index ? "error" : "default"}
              onClick={(event) => setEditing({ index, anchor: event.currentTarget, term })}
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
              sx={{ maxWidth: "100%", height: "auto", minHeight: 26, "& .MuiChip-label": { whiteSpace: "normal", overflowWrap: "anywhere", py: 0.25 } }}
            />
          </li>
        ))}
      </Box>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: { sm: "flex-start" } }}>
        <TextField
          value={text}
          onChange={(event) => { setText(event.target.value); setProblem(null); }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          label="Add a term"
          placeholder={terms.length ? "Another spelling or alias" : "A word or phrase from the title"}
          error={problem !== null}
          helperText={problem ?? undefined}
          sx={{ flex: 1, maxWidth: 420 }}
          slotProps={{ htmlInput: { maxLength: termLimit(method), spellCheck: false, ...(method === "regex" && { style: { fontFamily: mono } }) } }}
        />
        <MethodSelect value={method} onChange={setMethod} label="Match" />
        <Button variant="outlined" color="inherit" startIcon={<Add />} onClick={() => add([text])} disabled={!text.trim()}
          sx={{ height: 40 }}>
          Add
        </Button>
      </Stack>
      <Popover open={editing !== null} anchorEl={editing?.anchor} onClose={() => setEditing(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        slotProps={{ paper: { sx: { p: 2, width: 360, border: 1, borderColor: "divider" } } }}>
        {editing && (
          <Stack component="form" spacing={1.5} onSubmit={(event) => {
            event.preventDefault();
            const value = editing.term.value.trim();
            if (value) onChange(terms.map((term, at) => (at === editing.index ? { ...editing.term, value } : term)));
            setEditing(null);
          }}>
            <Typography variant="subtitle2">Edit term</Typography>
            <MethodSelect value={editing.term.method} label="Match"
              onChange={(next) => setEditing({ ...editing, term: { ...editing.term, method: next } })} />
            <Typography variant="caption" color="textSecondary">{METHODS[editing.term.method].description}</Typography>
            <TextField label="Term" value={editing.term.value} autoFocus fullWidth
              onChange={(event) => setEditing({ ...editing, term: { ...editing.term, value: event.target.value } })}
              slotProps={{ htmlInput: { maxLength: termLimit(editing.term.method), spellCheck: false } }} />
            <Stack direction="row" spacing={1} sx={{ justifyContent: "flex-end" }}>
              <Button color="inherit" onClick={() => {
                onChange(terms.filter((_, at) => at !== editing.index));
                setEditing(null);
              }}>Remove</Button>
              <Button type="submit" variant="contained" disabled={!editing.term.value.trim()}>Save</Button>
            </Stack>
          </Stack>
        )}
      </Popover>
    </Box>
  );
}
