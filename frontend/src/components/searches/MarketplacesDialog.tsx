import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { refreshSearches, useSession } from "../../api/hooks";
import type { AlertSummary, Source } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { SOURCES } from "../../lib/vocabulary";
import { ConfirmDialog } from "../common/Feedback";
import { useNotify } from "../common/notify";

const ORDER = Object.keys(SOURCES) as Source[];

interface Props {
  alert: AlertSummary | null;
  onClose: () => void;
}

/** /marketplaces: which marketplaces a search checks. Turning every one off pauses the search. */
export function MarketplacesDialog({ alert, onClose }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const enabled = useSession().data?.enabled_sources;
  // The person's unsaved choice; until they touch a switch, the search's saved set shows.
  const [draft, setDraft] = useState<{ id: string; sources: Source[] } | null>(null);
  const selected = alert && draft?.id === alert.id ? draft.sources : alert?.sources ?? [];
  const save = useMutation({
    mutationFn: (sources: Source[]) => api.setSources(alert!.id, sources),
    onSuccess: () => {
      refreshSearches(client);
      notify(`Saved the marketplaces for ${alert!.search_query}.`, "success");
      close();
    },
  });
  const close = () => {
    save.reset();
    setDraft(null);
    onClose();
  };
  const searched = (source: Source) => !enabled || enabled.includes(source);
  const chosen = ORDER.filter((source) => selected.includes(source));
  const changed = alert !== null && (chosen.length !== alert.sources.length || chosen.some((source) => !alert.sources.includes(source)));
  const toggle = (source: Source, on: boolean) =>
    setDraft({ id: alert!.id, sources: on ? [...selected, source] : selected.filter((item) => item !== source) });
  return (
    <ConfirmDialog open={alert !== null} title={`Marketplaces to check for ${alert?.search_query ?? "this search"}`} confirm="Save"
      busy={save.isPending} confirmDisabled={!changed} maxWidth="sm" onClose={close} onConfirm={() => save.mutate(chosen)}>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Choose the marketplaces this search checks. Nothing changes until you save; Save applies your choice from the
        search's next check. A marketplace you turn on starts quietly: its next check saves the listings it has now without
        posting them, and later checks post only new listings. A marketplace you turn off is no longer checked; its saved
        listings and posts stay. With none turned on, the search is paused. This does what /marketplaces does in Discord.
      </Typography>
      <Box sx={{ display: "grid", gap: 0.5 }}>
        {ORDER.map((source) => (
          <Box key={source}>
            <FormControlLabel label={SOURCES[source]}
              control={<Switch checked={selected.includes(source)} onChange={(_, on) => toggle(source, on)} />} />
            {!searched(source) && (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", ml: 6, mt: -0.5 }}>
                Off for the whole bot: this choice applies once the bot searches it
              </Typography>
            )}
          </Box>
        ))}
      </Box>
      {chosen.length === 0 ? (
        <Alert severity="warning" sx={{ mt: 2 }}>
          With no marketplace chosen, this search is paused: it checks nothing and posts nothing until you turn one on.
        </Alert>
      ) : !chosen.some(searched) && (
        <Alert severity="warning" sx={{ mt: 2 }}>This search checks no marketplace the bot searches, so it posts nothing.</Alert>
      )}
      {save.isError && <Alert severity="error" sx={{ mt: 2 }}>{errorMessage(save.error)}</Alert>}
    </ConfirmDialog>
  );
}
