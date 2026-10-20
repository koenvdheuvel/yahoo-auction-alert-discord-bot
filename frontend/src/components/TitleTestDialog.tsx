import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useMutation } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { api } from "../api/client";
import type { AlertSummary, Source } from "../api/types";
import { errorMessage } from "../lib/errors";
import type { Draft } from "../lib/useDraft";
import { SOURCES } from "../lib/vocabulary";
import { ReasonList, VerdictText } from "./common/Decision";
import { SheetDialog } from "./common/Sheet";

export interface TitleSeed {
  title?: string;
  source?: Source;
  price?: number | null;
}

/** One opening of the dialog. A new id starts a fresh form. */
export interface TitleTest {
  id: number;
  seed: TitleSeed;
  open: boolean;
}

interface FormProps {
  seed: TitleSeed;
  alert: AlertSummary | null;
  draft: Draft;
  onClose: () => void;
}

function TitleTestForm({ seed, alert, draft, onClose }: FormProps) {
  const [title, setTitle] = useState(seed.title ?? "");
  const [source, setSource] = useState<Source>(seed.source ?? "mercari");
  const [price, setPrice] = useState(typeof seed.price === "number" ? String(seed.price) : "0");
  const preview = useMutation({ mutationFn: api.preview });

  const priceValue = Number(price);
  const priceValid = price.trim() !== "" && Number.isInteger(priceValue) && priceValue >= 0;
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (!title.trim() || !priceValid) return;
    preview.mutate({ ruleset: draft.ruleset, title, source, price: priceValue, stock: 1,
      ...(alert ? { alert_id: alert.id } : {}) });
  };

  const decision = preview.data?.decision;
  return (
    // A flex column, so the content scrolls and the buttons stay in sight, also above the on-screen keyboard.
    <Box component="form" onSubmit={submit} noValidate sx={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <DialogTitle id="title-test-title">Test a title</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2 }}>
        <Typography variant="body2" color="textSecondary">
          {alert
            ? `Checks a title against your draft for “${alert.search_query}” and its enabled Discord filters. Nothing is saved or sent.`
            : "Checks a title against your scratch draft. Choose a search to include its Discord filters. Nothing is saved or sent."}
        </Typography>
        <TextField label="Listing title" value={title} onChange={(event) => setTitle(event.target.value)}
          multiline minRows={2} required autoFocus fullWidth slotProps={{ htmlInput: { maxLength: 10000 } }} />
        {/* On phones the marketplace gets more of the row than the short price. */}
        <Stack direction="row" spacing={1.5}>
          <TextField select label="Marketplace" value={source} onChange={(event) => setSource(event.target.value as Source)}
            sx={{ flex: { xs: 3, sm: 1 } }}>
            {(Object.keys(SOURCES) as Source[]).map((name) => <MenuItem key={name} value={name}>{SOURCES[name]}</MenuItem>)}
          </TextField>
          <TextField label="Price" value={price} onChange={(event) => setPrice(event.target.value)} sx={{ flex: { xs: 2, sm: 1 } }}
            error={!priceValid} helperText={priceValid ? undefined : "Enter a whole number of yen"}
            slotProps={{ htmlInput: { inputMode: "numeric" }, input: { startAdornment: <InputAdornment position="start">¥</InputAdornment> } }} />
        </Stack>
        {preview.isError && <Alert severity="error">{errorMessage(preview.error)}</Alert>}
        {decision && (
          <Box aria-live="polite" sx={{ borderTop: 1, borderColor: "divider", pt: 2, display: "grid", gap: 1 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <VerdictText verdict={decision.verdict} />
              <Typography variant="body2" color="textSecondary">with your draft</Typography>
            </Stack>
            <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
              <Box component="span" sx={{ color: "text.secondary" }}>Compared title: </Box>{decision.normalized_title || title}
            </Typography>
            <ReasonList reasons={decision.reasons} />
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} color="inherit">Close</Button>
        <Button type="submit" variant="contained" disabled={!title.trim() || !priceValid || preview.isPending || !draft.ready}>
          {preview.isPending ? "Testing" : "Test"}
        </Button>
      </DialogActions>
    </Box>
  );
}

interface Props {
  test: TitleTest | null;
  alert: AlertSummary | null;
  draft: Draft;
  onClose: () => void;
}

export function TitleTestDialog({ test, alert, draft, onClose }: Props) {
  return (
    <SheetDialog open={test?.open ?? false} onClose={onClose} maxWidth="sm" aria-labelledby="title-test-title">
      {test && <TitleTestForm key={test.id} seed={test.seed} alert={alert} draft={draft} onClose={onClose} />}
    </SheetDialog>
  );
}
