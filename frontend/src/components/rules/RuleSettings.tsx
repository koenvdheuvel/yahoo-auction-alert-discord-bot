import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import Box from "@mui/material/Box";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../../api/client";
import { keys } from "../../api/hooks";
import { errorMessage } from "../../lib/errors";
import { ConfirmDialog } from "../common/Feedback";
import { useNotify } from "../common/notify";

import type { DiscordFilter, Normalization, Ruleset, Source } from "../../api/types";
import { formatCount } from "../../lib/format";
import { useTouch } from "../../lib/responsive";
import { SOURCES } from "../../lib/vocabulary";
import { figures, mono } from "../../theme";

const NORMALIZATION: [keyof Normalization, string, string][] = [
  ["nfkc", "Character width", "ＰＯＳＴＥＲ and POSTER match; so do ﾎﾟｽﾀｰ and ポスター."],
  ["casefold", "Letter case", "Poster, POSTER and poster match."],
  ["collapse_whitespace", "Spaces", "Repeated spaces and line breaks count as one space."],
  ["kana_fold", "Hiragana and katakana", "ぽすたー and ポスター match. It does not translate or guess readings."],
];

function Section({ title, children, hint }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ py: 2, borderTop: 1, borderColor: "divider", "&:first-of-type": { borderTop: 0, pt: 0 } }}>
      <Typography variant="h3" component="h3">{title}</Typography>
      {hint && <Typography variant="body2" color="textSecondary" sx={{ mt: 0.5 }}>{hint}</Typography>}
      <Box sx={{ mt: 1.25 }}>{children}</Box>
    </Box>
  );
}

const METHOD_NAMES: Record<string, string> = { regex: "regex", text: "text", legacy: "unknown-type" };

function describeFilter(filter: DiscordFilter): string {
  const kind = `${filter.policy === "blacklist" ? "Blocks" : "Allows"} ${METHOD_NAMES[filter.method] ?? filter.method} matches`;
  const matched = `matched ${formatCount(filter.matches)} ${filter.matches === 1 ? "time" : "times"}`;
  if (!filter.enabled) {
    return `${kind}, ${matched}. Disabled: the old database lost whether it was text or a regex. To keep it, ` +
      "add the term to a group above, then delete this filter.";
  }
  return `${kind}, ${matched}.`;
}

/** /filters delete, after asking. */
function DeleteFilter({ alertId, filter, canChange }: { alertId: string; filter: DiscordFilter; canChange: boolean }) {
  const client = useQueryClient();
  const notify = useNotify();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.deleteLegacyFilter(alertId, filter.id),
    onSuccess: () => {
      setConfirming(false);
      notify(`Deleted filter ${filter.id}.`, "success");
      void client.invalidateQueries({ queryKey: keys.rules(alertId) });
    },
    onError: (error) => notify(errorMessage(error), "error"),
  });
  return (
    <>
      <Tooltip title={canChange ? "Delete, like /filters delete" : "You need Manage Channels in this search's channel"}>
        <span>
          <IconButton size="small" aria-label={`Delete filter ${filter.value}`} disabled={!canChange}
            onClick={() => setConfirming(true)}><DeleteOutlined fontSize="small" /></IconButton>
        </span>
      </Tooltip>
      <ConfirmDialog open={confirming} title="Delete this Discord filter?" confirm="Delete" busy={remove.isPending} danger
        onClose={() => setConfirming(false)} onConfirm={() => remove.mutate()}>
        <Typography variant="body2">
          “{filter.value}” stops applying to this search, as with /filters delete {filter.id}. Published rule versions
          do not change.
        </Typography>
      </ConfirmDialog>
    </>
  );
}

function parseBound(value: string): number | null | undefined {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 ? number : undefined;
}

interface Props {
  ruleset: Ruleset;
  onChange: (ruleset: Ruleset) => void;
  filters: DiscordFilter[] | null;
  /** The search the filters belong to, for deleting them. */
  alertId?: string | null;
  canChange?: boolean;
  priceError: string | null;
}

export function RuleSettings({ ruleset, onChange, filters, alertId = null, canChange = false, priceError }: Props) {
  const touch = useTouch();
  const set = (changes: Partial<Ruleset>) => onChange({ ...ruleset, ...changes });
  const toggleSource = (source: Source, on: boolean) =>
    set({ sources: on ? [...ruleset.sources, source] : ruleset.sources.filter((value) => value !== source) });
  const bound = (key: "min" | "max", text: string) => {
    const value = parseBound(text);
    if (value !== undefined) set({ price: { ...ruleset.price, [key]: value } });
  };

  return (
    <Box>
      <Section title="Title comparison" hint="Groups that compare the normalized title see it changed like this. The original title is kept.">
        <FormGroup sx={{ gap: 1 }}>
          {NORMALIZATION.map(([key, name, example]) => (
            <FormControlLabel key={key} sx={{ alignItems: "flex-start", m: 0 }}
              control={<Switch size="small" checked={ruleset.normalization[key]} sx={{ mt: 0.25 }}
                onChange={(event) => set({ normalization: { ...ruleset.normalization, [key]: event.target.checked } })} />}
              label={<Box sx={{ ml: 1 }}><Typography variant="body2" sx={{ fontWeight: 600 }}>{name}</Typography>
                <Typography variant="caption" color="textSecondary">{example}</Typography></Box>} />
          ))}
        </FormGroup>
      </Section>
      <Section title="Marketplaces" hint="With none ticked, listings from every marketplace are allowed.">
        <FormGroup row>
          {(Object.keys(SOURCES) as Source[]).map((source) => (
            <FormControlLabel key={source} label={SOURCES[source]} slotProps={{ typography: { variant: "body2" } }}
              control={<Checkbox size="small" checked={ruleset.sources.includes(source)}
                onChange={(event) => toggleSource(source, event.target.checked)} />} />
          ))}
        </FormGroup>
      </Section>
      <Section title="Price" hint="Listings outside these prices are filtered. Leave a field empty for no limit.">
        <Stack direction="row" spacing={1.5}>
          {(["min", "max"] as const).map((key) => (
            <TextField key={key} label={key === "min" ? "At least" : "At most"} value={ruleset.price[key] ?? ""}
              onChange={(event) => bound(key, event.target.value)} sx={{ flex: 1 }}
              error={Boolean(priceError)} placeholder="No limit"
              slotProps={{ htmlInput: { inputMode: "numeric", style: { fontVariantNumeric: "tabular-nums" } },
                input: { startAdornment: <InputAdornment position="start">¥</InputAdornment> } }} />
          ))}
        </Stack>
        {priceError && <Typography variant="caption" color="error" sx={{ mt: 0.75, display: "block" }}>{priceError}</Typography>}
      </Section>
      <Section title="Discord filters" hint="Filters added with /filters keep their exact, case-sensitive matching.">
        <FormControlLabel label="Apply them alongside these rules" slotProps={{ typography: { variant: "body2" } }}
          control={<Switch size="small" checked={ruleset.include_legacy} onChange={(event) => set({ include_legacy: event.target.checked })} />} />
        {filters === null ? (
          <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>Choose a search to see its Discord filters.</Typography>
        ) : filters.length === 0 ? (
          <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>This search has no Discord filters.</Typography>
        ) : (
          <>
            <Box component="ul" sx={{ listStyle: "none", p: 0, m: 0, mt: 1, display: "grid", gap: 1 }}>
              {filters.map((filter) => (
                <Box component="li" key={filter.id} sx={{ display: "flex", gap: 1, alignItems: "flex-start" }}>
                  <Box sx={{ flex: 1, minWidth: 0, opacity: filter.enabled && ruleset.include_legacy ? 1 : 0.65 }}>
                    <Typography variant="body2" sx={{ fontFamily: filter.method === "regex" ? mono : undefined, overflowWrap: "anywhere" }}>
                      {filter.value}
                    </Typography>
                    <Typography variant="caption" color="textSecondary" sx={figures}>
                      Filter {filter.id}: {describeFilter(filter)}
                    </Typography>
                  </Box>
                  {alertId && <DeleteFilter alertId={alertId} filter={filter} canChange={canChange} />}
                </Box>
              ))}
            </Box>
            {/* Tooltips do not open from a tap, so touch screens say here why deleting is off. */}
            {alertId && !canChange && touch && (
              <Typography variant="caption" color="textSecondary" component="p" sx={{ mt: 1 }}>
                You need Manage Channels in this search's channel to delete filters.
              </Typography>
            )}
          </>
        )}
      </Section>
    </Box>
  );
}
