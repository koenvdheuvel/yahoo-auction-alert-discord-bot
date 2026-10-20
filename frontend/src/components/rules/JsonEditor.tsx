import ExpandMore from "@mui/icons-material/ExpandMore";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import type { Ruleset } from "../../api/types";
import { canonical, parseRuleset } from "../../lib/ruleset";
import { mono } from "../../theme";

interface Props {
  ruleset: Ruleset;
  onApply: (ruleset: Ruleset) => void;
  disabled: boolean;
}

/** The same draft as JSON, for pasting rules between searches. */
export function JsonEditor({ ruleset, onApply, disabled }: Props) {
  const current = JSON.stringify(canonical(ruleset), null, 2);
  const [text, setText] = useState(current);
  const [shown, setShown] = useState(current);
  const [error, setError] = useState<string | null>(null);
  // Follow edits made above, unless there are unapplied edits here.
  if (current !== shown) {
    setShown(current);
    if (text === shown) setText(current);
  }
  const changed = text !== current;

  const apply = () => {
    try {
      onApply(parseRuleset(text));
      setError(null);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The JSON could not be read.");
    }
  };

  return (
    <Accordion disableGutters variant="outlined" sx={{ borderRadius: 1, "&::before": { display: "none" } }}>
      <AccordionSummary expandIcon={<ExpandMore />}>
        <Typography variant="subtitle2" component="span">Edit as JSON</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ display: "grid", gap: 1.5 }}>
        <Typography variant="body2" color="textSecondary">
          Copy the draft to another search, or paste rules in. Applying replaces the draft; nothing is published.
        </Typography>
        <TextField value={text} onChange={(event) => { setText(event.target.value); setError(null); }} multiline minRows={10}
          maxRows={28} fullWidth disabled={disabled} label="Rules as JSON"
          slotProps={{ htmlInput: { spellCheck: false, style: { fontFamily: mono, fontSize: 12.5 } } }} />
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" color="inherit" onClick={apply} disabled={disabled || !changed}>Apply to draft</Button>
          <Button color="inherit" onClick={() => { setText(current); setError(null); }} disabled={!changed}>Undo JSON edits</Button>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
