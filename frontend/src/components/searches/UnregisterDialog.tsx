import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Skeleton from "@mui/material/Skeleton";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import { refreshSearches, useAlertDetail } from "../../api/hooks";
import type { AlertSummary } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { plural } from "../../lib/format";
import { ConfirmDialog, LoadError } from "../common/Feedback";
import { useNotify } from "../common/notify";

interface Props {
  alert: AlertSummary | null;
  onClose: () => void;
  onDone: () => void;
}

/** /unregister, after saying what happens to the posts and the history. */
export function UnregisterDialog({ alert, onClose, onDone }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const detail = useAlertDetail(alert?.id ?? null, alert !== null);
  const unregister = useMutation({
    mutationFn: () => api.unregister(alert!.id),
    onSuccess: () => {
      refreshSearches(client);
      notify(`Unregistered the search for ${alert!.search_query}.`, "success");
      onDone();
    },
  });
  const usage = detail.data?.usage;
  const close = () => {
    unregister.reset();
    onClose();
  };
  return (
    <ConfirmDialog open={alert !== null} title={`Unregister ${alert?.search_query ?? "this search"}?`} confirm="Unregister"
      busy={unregister.isPending} confirmDisabled={!detail.isSuccess} maxWidth="sm" danger onClose={close}
      onConfirm={() => unregister.mutate()}>
      {detail.isPending && <Skeleton variant="rounded" height={96} />}
      {detail.isError && <LoadError error={detail.error} what="The search" onRetry={() => void detail.refetch()} />}
      {usage && (
        <Box component="ul" sx={{ m: 0, pl: 2.5, display: "grid", gap: 0.75, "& li": { typography: "body2" } }}>
          <li>The bot stops checking the marketplaces for it, as with /unregister.</li>
          <li>
            {usage.posts
              ? `Its ${plural(usage.posts, "post")} stay in Discord. To remove them, use the channel's Cleanup tab first.`
              : "It has no posts in Discord."}
          </li>
          {usage.waiting_posts > 0 && <li>{plural(usage.waiting_posts, "post")} not sent yet are cancelled.</li>}
          {(usage.rule_versions > 0 || usage.archived > 0) && (
            <li>
              Its {plural(usage.rule_versions, "rule version")} and {plural(usage.archived, "saved listing")} are kept, but
              no longer belong to a search.
            </li>
          )}
          {usage.legacy_filters > 0 && <li>Its {plural(usage.legacy_filters, "Discord filter")} are deleted.</li>}
          <li>Hidden listings in the channel and 🔔 follows do not change.</li>
        </Box>
      )}
      {detail.data?.channel_deleted && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>Discord says its channel was deleted.</Typography>
      )}
      {unregister.isError && <Alert severity="error" sx={{ mt: 2 }}>{errorMessage(unregister.error)}</Alert>}
    </ConfirmDialog>
  );
}
