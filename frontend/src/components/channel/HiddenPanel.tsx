import MoreHoriz from "@mui/icons-material/MoreHoriz";
import OpenInNew from "@mui/icons-material/OpenInNew";
import VisibilityOutlined from "@mui/icons-material/VisibilityOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { keys, useHidden } from "../../api/hooks";
import type { StoredListing } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import { longPressable, useLongPress } from "../../lib/gestures";
import { useCompact } from "../../lib/responsive";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { EmptyState, LoadError } from "../common/Feedback";
import { ListingImage } from "../common/ListingImage";
import { useNotify } from "../common/notify";
import { ActionSheet, type SheetAction } from "../common/Sheet";

interface RowProps {
  item: StoredListing;
  compact: boolean;
  /** Its sheet is open, so the row stays marked. */
  active: boolean;
  canChange: boolean;
  busy: boolean;
  onUnhide: () => void;
  onMenu: () => void;
}

/** One hidden listing. On phones and tablets it is a roomy row; a long press opens its actions. */
function HiddenRow({ item, compact, active, canChange, busy, onUnhide, onMenu }: RowProps) {
  const press = useLongPress(onMenu);
  const url = safeUrl(item.url);
  const title = item.title || item.external_id;
  const showAgain = (
    <Button size="small" variant="outlined" color="inherit" disabled={!canChange || busy} onClick={onUnhide}
      sx={{ flex: "none" }}>Show again</Button>
  );

  if (!compact) {
    return (
      <Box component="li" {...press} sx={{ display: "grid", gridTemplateColumns: "48px minmax(0, 1fr) auto",
        gap: 1.5, alignItems: "center", p: 1, borderRadius: 1, "&:hover": { bgcolor: "surface.hover" }, ...longPressable }}>
        <ListingImage src={item.image_url} size={48} />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body1" noWrap title={item.title} sx={{ fontWeight: 600 }}>{title}</Typography>
          <Typography variant="caption" color="textSecondary" sx={figures}>
            {sourceName(item.source)}, {formatPrice(item.price)}, changed {formatRelative(item.updated_at)}
            {url && <> · <Link href={url} target="_blank" rel="noopener noreferrer">Listing</Link></>}
          </Typography>
        </Box>
        {showAgain}
      </Box>
    );
  }
  return (
    <Box component="li" {...press} sx={{ display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", columnGap: 1.5,
      alignItems: "start", py: 1, px: 1, mx: -1, borderRadius: 1, bgcolor: active ? "surface.hover" : undefined, ...longPressable }}>
      <ListingImage src={item.image_url} size={64} />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body1" sx={{ fontWeight: 600, overflowWrap: "anywhere", display: "-webkit-box", WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical", overflow: "hidden" }}>{title}</Typography>
        <Typography variant="body2" color="textSecondary" sx={figures}>
          {sourceName(item.source)}, {formatPrice(item.price)} · changed {formatRelative(item.updated_at)}
        </Typography>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 1 }}>
          {showAgain}
          <IconButton aria-label={`More for ${title}`} aria-haspopup="dialog" onClick={onMenu}><MoreHoriz /></IconButton>
        </Box>
      </Box>
    </Box>
  );
}

/** Listings hidden in the channel with 🗑️, and a way to show them again. */
export function HiddenPanel({ channelId, canChange }: { channelId: string; canChange: boolean }) {
  const client = useQueryClient();
  const notify = useNotify();
  const compact = useCompact();
  const hidden = useHidden(channelId);
  // The listing stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ item: StoredListing; open: boolean } | null>(null);
  const unhide = useMutation({
    mutationFn: (itemId: string) => api.unhide(channelId, itemId),
    onSuccess: () => {
      notify("Shown again. It is posted here the next time it changes.", "success");
      for (const key of [keys.hidden(channelId), keys.allPosts, keys.allChannels]) void client.invalidateQueries({ queryKey: key });
    },
    onError: (error) => notify(errorMessage(error), "error"),
  });
  if (hidden.isPending) {
    return <Stack spacing={1}>{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} variant="rounded" height={compact ? 112 : 56} />)}</Stack>;
  }
  if (hidden.isError) return <LoadError error={hidden.error} what="Hidden listings" onRetry={() => void hidden.refetch()} />;
  if (!hidden.data.items.length) {
    return <EmptyState title="Nothing hidden">Listings someone removed with 🗑️, or hid from the Posts tab, are listed here.</EmptyState>;
  }
  const picked = menu?.item;
  const pickedUrl = picked ? safeUrl(picked.url) : null;
  const actions: SheetAction[] = picked ? [
    ...(pickedUrl ? [{ label: "Open the listing", icon: <OpenInNew />, href: pickedUrl }] : []),
    { label: "Show again", icon: <VisibilityOutlined />, onSelect: () => unhide.mutate(picked.item_id), disabled: !canChange || unhide.isPending },
  ] : [];
  return (
    <>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 1.5 }}>
        {plural(hidden.data.total, "listing is", "listings are")} hidden here, so the bot does not post them in this
        channel. Showing one again does not post it right away; its next change is posted.
      </Typography>
      <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 0.5 }}>
        {hidden.data.items.map((item) => (
          <HiddenRow key={item.item_id} item={item} compact={compact} canChange={canChange} busy={unhide.isPending}
            active={menu?.open === true && menu.item.item_id === item.item_id}
            onUnhide={() => unhide.mutate(item.item_id)} onMenu={() => setMenu({ item, open: true })} />
        ))}
      </Box>
      <ActionSheet open={menu?.open ?? false} onClose={() => setMenu((current) => current && { ...current, open: false })}
        title={picked ? picked.title || picked.external_id : ""} actions={actions}>
        {picked && (
          <Box sx={{ display: "flex", gap: 1.5, alignItems: "center", mt: 1 }}>
            <ListingImage src={picked.image_url} size={56} />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="textSecondary" sx={figures}>
                {sourceName(picked.source)}, {formatPrice(picked.price)}, changed {formatRelative(picked.updated_at)}
              </Typography>
              <Typography variant="caption" component="p" color="textSecondary">
                {canChange ? "Once it is shown again, its next change is posted here." : "You need Manage Channels here to show it again."}
              </Typography>
            </Box>
          </Box>
        )}
      </ActionSheet>
    </>
  );
}
