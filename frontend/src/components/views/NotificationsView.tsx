import ForumOutlined from "@mui/icons-material/ForumOutlined";
import MoreHoriz from "@mui/icons-material/MoreHoriz";
import NotificationsOffOutlined from "@mui/icons-material/NotificationsOffOutlined";
import OpenInNew from "@mui/icons-material/OpenInNew";
import Tag from "@mui/icons-material/Tag";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { useNotifications } from "../../api/hooks";
import type { HiddenSubscription, Subscription } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatDateTime, formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import { longPressable, useLongPress } from "../../lib/gestures";
import { discordLink } from "../../lib/removal";
import { useCompact } from "../../lib/responsive";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { useFollow } from "../common/follow";
import { EmptyState, LoadError } from "../common/Feedback";
import { FollowButton } from "../common/FollowButton";
import { ListingImage } from "../common/ListingImage";
import { ActionSheet, type SheetAction } from "../common/Sheet";

interface CardProps {
  item: Subscription;
  compact: boolean;
  /** Its sheet is open, so the card stays marked. */
  active: boolean;
  onOpenChannel: (guildId: string, channelId: string) => void;
  /** Whether you manage the server, so its channel page opens for you. */
  canOpen: (guildId: string) => boolean;
  onMenu: () => void;
}

function Card({ item, compact, active, onOpenChannel, canOpen, onMenu }: CardProps) {
  // A long press opens the links and Unfollow, like a long press on a message in Discord's app.
  const press = useLongPress(onMenu);
  const url = safeUrl(item.url);
  const title = item.title || item.external_id;
  const facts = (
    <Typography variant="body2" color="textSecondary" sx={figures}>
      {sourceName(item.source)}, {formatPrice(item.price)}
      {item.buyout_price > 0 && `, buyout ${formatPrice(item.buyout_price)}`}
      {item.stock > 1 && `, ${plural(item.stock, "in stock", "in stock")}`}
    </Typography>
  );
  const chips = (
    <>
      {item.end_time && <Chip variant="outlined" label={`Ends ${formatRelative(item.end_time)}`} title={formatDateTime(item.end_time)} />}
      {item.muted && <Chip variant="outlined" color="warning" label="Muted: no updates" />}
      {item.waiting_dms > 0 && <Chip variant="outlined" color="info" label={`${plural(item.waiting_dms, "DM")} on the way`} />}
    </>
  );
  const changed = `Changed ${formatRelative(item.updated_at)}, last seen ${formatRelative(item.last_seen_at)}`;

  if (compact) {
    return (
      <Paper component="li" {...press} sx={{ p: 1.5, bgcolor: active ? "surface.hover" : "background.paper", display: "grid",
        gridTemplateColumns: "64px minmax(0, 1fr)", columnGap: 1.5, alignItems: "start", ...longPressable }}>
        <ListingImage src={item.image_url} size={64} />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ overflowWrap: "anywhere", display: "-webkit-box", WebkitLineClamp: 3,
            WebkitBoxOrient: "vertical", overflow: "hidden" }}>{title}</Typography>
          {facts}
          {(item.end_time || item.muted || item.waiting_dms > 0) && (
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.75 }}>{chips}</Box>
          )}
          <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.75 }}>{changed}</Typography>
          {item.posts.length > 0 && (
            <Typography variant="caption" component="p" color="textSecondary">
              Posted in {item.posts.map((post) => channelLabel(post.channel_id, post.channel_name)).join(", ")}
            </Typography>
          )}
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 1 }}>
            <FollowButton itemId={item.item_id} following />
            <IconButton aria-label={`More for ${title}`} aria-haspopup="dialog" onClick={onMenu}><MoreHoriz /></IconButton>
          </Box>
        </Box>
      </Paper>
    );
  }
  return (
    <Paper component="li" {...press} sx={{ p: 1.5, bgcolor: "background.paper", display: "grid", gap: 1.5,
      gridTemplateColumns: { xs: "64px minmax(0, 1fr)", sm: "80px minmax(0, 1fr) auto" }, alignItems: "start", ...longPressable }}>
      <ListingImage src={item.image_url} size="100%" />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="subtitle1" sx={{ overflowWrap: "anywhere" }}>
          {url ? <Link href={url} target="_blank" rel="noopener noreferrer" color="inherit">{title}</Link> : title}
        </Typography>
        {facts}
        <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 0.75, flexWrap: "wrap", rowGap: 0.5, alignItems: "center" }}>
          {chips}
          <Typography variant="caption" color="textSecondary">{changed}</Typography>
        </Stack>
        {item.posts.length > 0 && (
          <Typography variant="caption" component="p" color="textSecondary" sx={{ mt: 0.75 }}>
            Posted in {item.posts.map((post, index) => {
              const discord = post.message_id ? discordLink(post.guild_id, post.channel_id, post.message_id) : null;
              const label = channelLabel(post.channel_id, post.channel_name);
              return (
                <Box component="span" key={post.channel_id}>
                  {index > 0 && ", "}
                  {canOpen(post.guild_id)
                    ? <Link component="button" variant="caption" onClick={() => onOpenChannel(post.guild_id, post.channel_id)}>{label}</Link>
                    : label}
                  {discord && <> (<Link href={discord} target="_blank" rel="noopener noreferrer" variant="caption">post</Link>)</>}
                </Box>
              );
            })}
          </Typography>
        )}
      </Box>
      <Box sx={{ gridColumn: { xs: "2", sm: "auto" } }}>
        <FollowButton itemId={item.item_id} following />
      </Box>
    </Paper>
  );
}

function HiddenCard({ item }: { item: HiddenSubscription }) {
  return (
    <Paper component="li" sx={{ p: 1.5, bgcolor: "background.paper", display: "flex", gap: 1.5, justifyContent: "space-between",
      flexDirection: { xs: "column", sm: "row" }, alignItems: { xs: "flex-start", sm: "center" } }}>
      <Typography variant="body2" color="textSecondary">
        A listing in a channel you can't see, or in a server you left. You still get its DMs.
      </Typography>
      <Box sx={{ flex: "none" }}><FollowButton itemId={item.item_id} following /></Box>
    </Paper>
  );
}

interface Props {
  /** Only the listings posted in this server, or every listing you follow when null. */
  guildId: string | null;
  /** Whether you manage a server, where the dashboard offers Follow on posts and listings. */
  followHere: boolean;
  onOpenChannel: (guildId: string, channelId: string) => void;
  canOpen: (guildId: string) => boolean;
}

/** Your own 🔔 notifications: the listings you get DMs for. */
export function NotificationsView({ guildId, followHere, onOpenChannel, canOpen }: Props) {
  const compact = useCompact();
  const follow = useFollow();
  const notifications = useNotifications(true);
  // The listing stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ item: Subscription; open: boolean } | null>(null);
  const items = (notifications.data?.items ?? []).filter((item) =>
    guildId === null || (!item.redacted && item.posts.some((post) => post.guild_id === guildId)));

  const picked = menu?.item;
  const pickedUrl = picked ? safeUrl(picked.url) : null;
  const actions: SheetAction[] = picked ? [
    ...(pickedUrl ? [{ label: "Open the listing", icon: <OpenInNew />, href: pickedUrl }] : []),
    ...picked.posts.flatMap((post): SheetAction[] => {
      const label = channelLabel(post.channel_id, post.channel_name);
      const discord = post.message_id ? discordLink(post.guild_id, post.channel_id, post.message_id) : null;
      return [
        ...(discord ? [{ label: `Open in Discord (${label})`, icon: <ForumOutlined />, href: discord }] : []),
        ...(canOpen(post.guild_id) ? [{ label: `Open ${label} in the dashboard`, icon: <Tag />,
          onSelect: () => onOpenChannel(post.guild_id, post.channel_id) }] : []),
      ];
    }),
    { label: "Stop following", icon: <NotificationsOffOutlined />, onSelect: () => follow.toggle(picked.item_id, true),
      disabled: follow.pending === picked.item_id },
  ] : [];

  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 2.5, maxWidth: 960 }}>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
        The bot sends you a DM when a listing you follow drops in price, changes its buyout price, or comes back in
        stock. Follow a listing with 🔔 under its post in Discord{followHere ? ", or from its post or listing here" : ""}. Only
        you see this list.
      </Typography>
      {notifications.isPending && <Stack spacing={1}>{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} variant="rounded" height={96} />)}</Stack>}
      {notifications.isError && <LoadError error={notifications.error} what="Your notifications" onRetry={() => void notifications.refetch()} />}
      {notifications.data && (items.length === 0 ? (
        <EmptyState title={guildId ? "You follow no listings from this server" : "You follow no listings"}>
          React with 🔔 under a listing's post in Discord to get a DM when it changes.
        </EmptyState>
      ) : (
        <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 1 }}>
          {items.map((item) => item.redacted
            ? <HiddenCard key={item.item_id} item={item} />
            : <Card key={item.item_id} item={item} compact={compact} active={menu?.open === true && menu.item.item_id === item.item_id}
              onOpenChannel={onOpenChannel} canOpen={canOpen} onMenu={() => setMenu({ item, open: true })} />)}
        </Box>
      ))}
      <ActionSheet open={menu?.open ?? false} onClose={() => setMenu((current) => current && { ...current, open: false })}
        title={picked ? picked.title || picked.external_id : ""} actions={actions}>
        {picked && (
          <Box sx={{ display: "flex", gap: 1.5, alignItems: "center", mt: 1 }}>
            <ListingImage src={picked.image_url} size={56} />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="textSecondary" sx={figures}>
                {sourceName(picked.source)}, {formatPrice(picked.price)}
              </Typography>
              {picked.end_time && (
                <Typography variant="caption" component="p" color="textSecondary">Ends {formatDateTime(picked.end_time)}.</Typography>
              )}
              <Typography variant="caption" component="p" color="textSecondary">
                You get a DM when its price, buyout price or stock changes.
              </Typography>
            </Box>
          </Box>
        )}
      </ActionSheet>
    </Box>
  );
}
