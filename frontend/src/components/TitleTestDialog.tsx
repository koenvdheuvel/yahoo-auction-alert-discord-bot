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

import { ApiError, api } from "../api/client";
import { useRules } from "../api/hooks";
import type { AlertSummary, Source } from "../api/types";
import { channelLabel } from "../lib/channels";
import { errorMessage } from "../lib/errors";
import { useDraft, type Draft } from "../lib/useDraft";
import { SOURCES } from "../lib/vocabulary";
import { ReasonList, VerdictText } from "./common/Decision";
import { LoadError } from "./common/Feedback";
import { SheetDialog } from "./common/Sheet";

export interface TitleSeed {
  title?: string;
  source?: Source;
  price?: number | null;
  /**
   * The search a listing belongs to, or null for a listing whose search is no longer registered. Left out when no listing
   * is tested: the test then starts with the search on screen, if any.
   */
  alertId?: string | null;
}

/** One opening of the dialog. A new id starts a fresh form. */
export interface TitleTest {
  id: number;
  seed: TitleSeed;
  open: boolean;
}

/** A search a title can be tested against, as the person knows it. */
interface Choice {
  id: string;
  query: string;
  channel: string;
}


/** Which rules a test with this draft applies. */
function rulesUsed(draft: Draft): string {
  if (draft.edited) return "your unpublished draft";
  return draft.published ? `published version ${draft.published.version}` : "the default rules";
}

type Body = Parameters<typeof api.preview>[0];

/**
 * One test and what it was asked. Its answer only shows while the form still asks the same, so changing the search, the
 * rules or the listing never leaves an earlier answer on screen, and an answer that arrives late is never shown.
 */
interface Asked {
  key: string;
  search: Choice;
  rules: string;
  body: Body;
}

interface FormProps {
  seed: TitleSeed;
  alert: AlertSummary | null;
  alerts: AlertSummary[];
  onClose: () => void;
}

function TitleTestForm({ seed, alert, alerts, onClose }: FormProps) {
  // A listing is tested with its own search, even when it has none. Otherwise the search on screen, or none until one is chosen.
  const [selected, setSelected] = useState<string | null>(seed.alertId === undefined ? alert?.id ?? null : seed.alertId);
  const [title, setTitle] = useState(seed.title ?? "");
  const [source, setSource] = useState<Source>(seed.source ?? "mercari");
  const [price, setPrice] = useState(typeof seed.price === "number" ? String(seed.price) : "0");
  // The same rules and draft the Rules tab shows for that search, unsaved edits included.
  const rules = useRules(selected);
  const draft = useDraft(selected, rules.data);
  const preview = useMutation({ mutationFn: (asked: Asked) => api.preview(asked.body) });

  const listed: Choice[] = alerts.map(({ id, search_query, channel_id, channel_name }) => ({
    id, query: search_query, channel: channelLabel(channel_id, channel_name),
  }));
  // A search the list does not hold, such as one still loading, is named by what its rules say.
  const named = selected === null ? null : listed.find((choice) => choice.id === selected)
    ?? (rules.data ? { id: selected, query: rules.data.alert.search_query, channel: channelLabel(rules.data.alert.channel_id, null) } : null);
  const choices = named && !listed.includes(named) ? [...listed, named] : listed;
  const target = selected !== null && named !== null && draft.ready ? { id: selected, search: named } : null;
  const loading = selected !== null && rules.data === undefined && !rules.isError;
  const failed = selected !== null && rules.data === undefined && rules.isError;
  const gone = rules.error instanceof ApiError && (rules.error.status === 404 || rules.error.status === 403);

  const priceValue = Number(price);
  const priceValid = price.trim() !== "" && Number.isInteger(priceValue) && priceValue >= 0;
  const key = JSON.stringify([selected, title, source, price, draft.serialized]);
  const mine = preview.variables?.key === key ? preview.variables : null;
  const decision = mine && preview.isSuccess ? preview.data.decision : null;
  const asking = mine !== null && preview.isPending;

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (!target || !title.trim() || !priceValid || asking) return;
    preview.mutate({ key, search: target.search, rules: rulesUsed(draft),
      body: { ruleset: draft.ruleset, title, source, price: priceValue, stock: 1, alert_id: target.id } });
  };

  const hint = choices.length === 0 ? "There are no searches to test against."
    : selected === null
      ? seed.alertId === null ? "This listing's search is no longer registered. Choose a search to test it against."
        : "Choose the search whose rules to test against."
      : loading ? "Loading this search's rules."
        : target ? `Uses ${rulesUsed(draft)}${draft.ruleset.include_legacy
          ? " and this search's enabled Discord filters." : ". The rules turn Discord filters off."}`
          : undefined;

  return (
    // A flex column, so the content scrolls and the buttons stay in sight, also above the on-screen keyboard.
    <Box component="form" onSubmit={submit} noValidate sx={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <DialogTitle id="title-test-title">Test a title</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2 }}>
        <Typography variant="body2" color="textSecondary">
          Checks a title against the rules of one search: your unpublished draft if it has one, otherwise its published
          rules, with the search's enabled Discord filters. Nothing is saved or sent.
        </Typography>
        <TextField select label="Search" value={named?.id ?? ""} onChange={(event) => setSelected(event.target.value)}
          required fullWidth autoFocus={selected === null} disabled={choices.length === 0} helperText={hint}
          slotProps={{ select: { renderValue: (value) => {
            const choice = choices.find((item) => item.id === value);
            return choice ? `${choice.query} · ${choice.channel}` : "";
          } } }}>
          {choices.map((choice) => (
            <MenuItem key={choice.id} value={choice.id}>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" noWrap>{choice.query}</Typography>
                <Typography variant="caption" color="textSecondary">{choice.channel}</Typography>
              </Box>
            </MenuItem>
          ))}
        </TextField>
        {failed && (gone ? (
          <Alert severity="warning">
            This search is not available. It may have been unregistered, or you may not have access to it. Choose another search.
          </Alert>
        ) : <LoadError error={rules.error} what="The rules" onRetry={() => void rules.refetch()} />)}
        <TextField label="Listing title" value={title} onChange={(event) => setTitle(event.target.value)}
          multiline minRows={2} required autoFocus={selected !== null} fullWidth slotProps={{ htmlInput: { maxLength: 10000 } }} />
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
        {mine && preview.isError && <Alert severity="error">{errorMessage(preview.error)}</Alert>}
        {decision && mine && (
          <Box aria-live="polite" sx={{ borderTop: 1, borderColor: "divider", pt: 2, display: "grid", gap: 1 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <VerdictText verdict={decision.verdict} />
              <Typography variant="body2" color="textSecondary">
                with {mine.rules} for “{mine.search.query}” in {mine.search.channel}
              </Typography>
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
        <Button type="submit" variant="contained" disabled={!target || !title.trim() || !priceValid || asking}>
          {asking ? "Testing" : "Test"}
        </Button>
      </DialogActions>
    </Box>
  );
}

interface Props {
  test: TitleTest | null;
  /** The search on screen, which a test without a listing starts with. */
  alert: AlertSummary | null;
  /** The searches a title can be tested against. */
  alerts: AlertSummary[];
  onClose: () => void;
}

export function TitleTestDialog({ test, alert, alerts, onClose }: Props) {
  return (
    <SheetDialog open={test?.open ?? false} onClose={onClose} maxWidth="sm" aria-labelledby="title-test-title">
      {test && <TitleTestForm key={test.id} seed={test.seed} alert={alert} alerts={alerts} onClose={onClose} />}
    </SheetDialog>
  );
}
