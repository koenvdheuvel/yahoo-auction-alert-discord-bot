import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import { keys, useHidden } from "../../api/hooks";
import { errorMessage } from "../../lib/errors";
import { formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { EmptyState, LoadError } from "../common/Feedback";
import { ListingImage } from "../common/ListingImage";
import { useNotify } from "../common/notify";

/** Listings hidden in the channel with 🗑️, and a way to show them again. */
export function HiddenPanel({ channelId, canChange }: { channelId: string; canChange: boolean }) {
  const client = useQueryClient();
  const notify = useNotify();
  const hidden = useHidden(channelId);
  const unhide = useMutation({
    mutationFn: (itemId: string) => api.unhide(channelId, itemId),
    onSuccess: () => {
      notify("Shown again. It is posted here the next time it changes.", "success");
      for (const key of [keys.hidden(channelId), keys.allPosts, keys.allChannels]) void client.invalidateQueries({ queryKey: key });
    },
    onError: (error) => notify(errorMessage(error), "error"),
  });
  if (hidden.isPending) return <Stack spacing={1}>{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} variant="rounded" height={56} />)}</Stack>;
  if (hidden.isError) return <LoadError error={hidden.error} what="Hidden listings" onRetry={() => void hidden.refetch()} />;
  if (!hidden.data.items.length) {
    return <EmptyState title="Nothing hidden">Listings someone removed with 🗑️, or hid from the Posts tab, are listed here.</EmptyState>;
  }
  return (
    <>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 1.5 }}>
        {plural(hidden.data.total, "listing is", "listings are")} hidden here, so the bot does not post them in this
        channel. Showing one again does not post it right away; its next change is posted.
      </Typography>
      <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 0.5 }}>
        {hidden.data.items.map((item) => {
          const url = safeUrl(item.url);
          return (
            <Box component="li" key={item.item_id} sx={{ display: "grid", gridTemplateColumns: "48px minmax(0, 1fr) auto",
              gap: 1.5, alignItems: "center", p: 1, borderRadius: 1, "&:hover": { bgcolor: "surface.hover" } }}>
              <ListingImage src={item.image_url} size={48} />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body1" noWrap title={item.title} sx={{ fontWeight: 600 }}>{item.title || item.external_id}</Typography>
                <Typography variant="caption" color="textSecondary" sx={figures}>
                  {sourceName(item.source)}, {formatPrice(item.price)}, changed {formatRelative(item.updated_at)}
                  {url && <> · <Link href={url} target="_blank" rel="noopener noreferrer">Listing</Link></>}
                </Typography>
              </Box>
              <Button size="small" variant="outlined" color="inherit" disabled={!canChange || unhide.isPending}
                onClick={() => unhide.mutate(item.item_id)}>Show again</Button>
            </Box>
          );
        })}
      </Box>
    </>
  );
}
