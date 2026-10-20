import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useNotifications } from "../../api/hooks";
import type { HiddenSubscription, Subscription } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatDateTime, formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import { discordLink } from "../../lib/removal";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { EmptyState, LoadError } from "../common/Feedback";
import { FollowButton } from "../common/FollowButton";
import { ListingImage } from "../common/ListingImage";

interface CardProps {
  item: Subscription;
  onOpenChannel: (guildId: string, channelId: string) => void;
  /** Whether you manage the server, so its channel page opens for you. */
  canOpen: (guildId: string) => boolean;
}

function Card({ item, onOpenChannel, canOpen }: CardProps) {
  const url = safeUrl(item.url);
  return (
    <Paper component="li" sx={{ p: 1.5, bgcolor: "background.paper", display: "grid", gap: 1.5,
      gridTemplateColumns: { xs: "64px minmax(0, 1fr)", sm: "80px minmax(0, 1fr) auto" }, alignItems: "start" }}>
      <ListingImage src={item.image_url} size="100%" />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="subtitle1" sx={{ overflowWrap: "anywhere" }}>
          {url ? <Link href={url} target="_blank" rel="noopener noreferrer" color="inherit">{item.title || item.external_id}</Link> : item.title || item.external_id}
        </Typography>
        <Typography variant="body2" color="textSecondary" sx={figures}>
          {sourceName(item.source)}, {formatPrice(item.price)}
          {item.buyout_price > 0 && `, buyout ${formatPrice(item.buyout_price)}`}
          {item.stock > 1 && `, ${plural(item.stock, "in stock", "in stock")}`}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 0.75, flexWrap: "wrap", rowGap: 0.5, alignItems: "center" }}>
          {item.end_time && <Chip variant="outlined" label={`Ends ${formatRelative(item.end_time)}`} title={formatDateTime(item.end_time)} />}
          {item.muted && <Chip variant="outlined" color="warning" label="Muted: no updates" />}
          {item.waiting_dms > 0 && <Chip variant="outlined" color="info" label={`${plural(item.waiting_dms, "DM")} on the way`} />}
          <Typography variant="caption" color="textSecondary">
            Changed {formatRelative(item.updated_at)}, last seen {formatRelative(item.last_seen_at)}
          </Typography>
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
    <Paper component="li" sx={{ p: 1.5, bgcolor: "background.paper", display: "flex", gap: 1.5, alignItems: "center",
      justifyContent: "space-between" }}>
      <Typography variant="body2" color="textSecondary">
        A listing in a channel you can't see, or in a server you left. You still get its DMs.
      </Typography>
      <FollowButton itemId={item.item_id} following />
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
  const notifications = useNotifications(true);
  const items = (notifications.data?.items ?? []).filter((item) =>
    guildId === null || (!item.redacted && item.posts.some((post) => post.guild_id === guildId)));
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
            : <Card key={item.item_id} item={item} onOpenChannel={onOpenChannel} canOpen={canOpen} />)}
        </Box>
      ))}
    </Box>
  );
}
