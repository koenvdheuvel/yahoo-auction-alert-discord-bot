import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { keys, useSession } from "../api/hooks";
import { errorMessage } from "../lib/errors";
import { plural } from "../lib/format";
import { ConfirmDialog } from "./common/Feedback";
import { useNotify } from "./common/notify";

export function ImportHistoryDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const notify = useNotify();
  const discord = Boolean(useSession().data?.user);
  const importing = useMutation({
    mutationFn: api.importHistory,
    onSuccess: (result) => {
      onClose();
      const already = result.skipped ? ` ${plural(result.skipped, "listing was", "listings were")} already here or unreadable.` : "";
      notify(`Imported ${plural(result.imported, "listing")}.${already}`);
      void client.invalidateQueries({ queryKey: keys.allCandidates });
      void client.invalidateQueries({ queryKey: keys.alerts });
    },
    onError: (error) => notify(`Import failed: ${errorMessage(error)}`, "error"),
  });

  return (
    <ConfirmDialog open={open} title="Import saved history" confirm="Import" busy={importing.isPending}
      onConfirm={() => importing.mutate()} onClose={onClose}>
      <Typography variant="body2" sx={{ mb: 1.5 }}>
        Adds up to 1,000 recent listings the bot posted or tracked before candidate history existed. Running it
        again skips listings that are already here.
        {discord && " Only searches in the servers you manage are included."}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Their original decisions were not saved, so they come in as needing review. Listings that earlier filters
        rejected were never saved and cannot be recovered. Nothing is sent to Discord.
      </Typography>
    </ConfirmDialog>
  );
}
