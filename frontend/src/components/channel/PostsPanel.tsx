import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import ForumOutlined from "@mui/icons-material/ForumOutlined";
import MoreHoriz from "@mui/icons-material/MoreHoriz";
import NotificationsActive from "@mui/icons-material/NotificationsActive";
import NotificationsOffOutlined from "@mui/icons-material/NotificationsOffOutlined";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import OpenInNew from "@mui/icons-material/OpenInNew";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { keys, usePosts } from "../../api/hooks";
import type { ChannelPost } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { formatCount, formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import { longPressable, useLongPress } from "../../lib/gestures";
import { discordLink } from "../../lib/removal";
import { useCompact } from "../../lib/responsive";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { ConfirmDialog, EmptyState, LoadError } from "../common/Feedback";
import { FollowButton } from "../common/FollowButton";
import { ListingImage } from "../common/ListingImage";
import { useNotify } from "../common/notify";
import { ActionSheet, type SheetAction } from "../common/Sheet";
import { useFollow } from "../common/follow";

// Two lines of the title, then an ellipsis.
const twoLines = { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" } as const;

interface RowProps {
  post: ChannelPost;
  guildId: string | null;
  channelId: string;
  /** Whether 🔔 works for you here. */
  notifications: boolean;
  canManage: boolean;
  compact: boolean;
  /** Its sheet is open, so the row stays marked like a long-pressed message in Discord. */
  active: boolean;
  /** The 🔔 change for this post's listing is on its way. */
  followPending: boolean;
  onFollow: () => void;
  onHide: () => void;
  onMenu: () => void;
}

/** One post. On phones and tablets it is a roomy row with 🔔, 🗑️ and a button for the rest. */
function PostRow(props: RowProps) {
  const { post, guildId, channelId, notifications, canManage, compact, active, followPending, onFollow, onHide, onMenu } = props;
  // A long press opens the post's actions, like a long press on a message in Discord's app.
  const press = useLongPress(onMenu);
  const discord = discordLink(guildId, channelId, post.message_id);
  const url = safeUrl(post.listing.url);
  const title = post.listing.title;

  if (!compact) {
    return (
      <Box component="li" {...press} sx={{ display: "grid", gridTemplateColumns: "48px minmax(0, 1fr) auto",
        gap: 1.5, alignItems: "center", p: 1, borderRadius: 1, "&:hover": { bgcolor: "surface.hover" }, ...longPressable }}>
        <ListingImage src={post.listing.image_url} size={48} />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body1" noWrap title={title} sx={{ fontWeight: 600 }}>{title}</Typography>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 0.5 }}>
            <Typography variant="caption" color="textSecondary" sx={figures}>
              {sourceName(post.listing.source)}, {formatPrice(post.listing.price)}, posted {formatRelative(post.posted_at)}
            </Typography>
            {post.hidden && <Chip label="Hidden" color="warning" variant="outlined" />}
            {post.queued && <Chip label="Being removed" variant="outlined" />}
            {post.subscribers > 0 && (
              <Tooltip title="People who get DMs for this listing. Who they are is not shown.">
                <Chip label={`🔔 ${formatCount(post.subscribers)}`} variant="outlined" />
              </Tooltip>
            )}
            {discord && <Link href={discord} target="_blank" rel="noopener noreferrer" variant="caption">Open in Discord</Link>}
            {url && <Link href={url} target="_blank" rel="noopener noreferrer" variant="caption">Listing</Link>}
          </Stack>
        </Box>
        <Stack direction="row" spacing={0.5}>
          {notifications && <FollowButton itemId={post.item_id} following={post.subscribed_by_me} compact />}
          <Tooltip title={canManage ? "Hide in this channel and remove its posts (like 🗑️)" : "You need Manage Channels in this channel"}>
            <span>
              <IconButton size="small" aria-label={`Hide ${title}`} disabled={!canManage || post.hidden} onClick={onHide}>
                <DeleteOutlined fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      </Box>
    );
  }

  const states = post.hidden || post.queued || post.subscribers > 0;
  return (
    <Box component="li" {...press} sx={{ display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", columnGap: 1.5,
      alignItems: "start", py: 1, px: 1, mx: -1, borderRadius: 1, bgcolor: active ? "surface.hover" : undefined, ...longPressable }}>
      <ListingImage src={post.listing.image_url} size={64} />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body1" sx={{ fontWeight: 600, overflowWrap: "anywhere", ...twoLines }}>{title}</Typography>
        <Typography variant="body2" color="textSecondary" sx={figures}>
          {sourceName(post.listing.source)}, {formatPrice(post.listing.price)} · {formatRelative(post.posted_at)}
        </Typography>
        {states && (
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.75 }}>
            {post.hidden && <Chip label="Hidden" color="warning" variant="outlined" />}
            {post.queued && <Chip label="Being removed" variant="outlined" />}
            {post.subscribers > 0 && <Chip label={`🔔 ${formatCount(post.subscribers)}`} variant="outlined" />}
          </Box>
        )}
        {/* The same reactions Discord puts under the post, where a thumb reaches them. */}
        <Box sx={{ display: "flex", gap: 1, mt: 0.5, ml: -1.5 }}>
          {notifications && (
            <IconButton aria-label={post.subscribed_by_me ? "Stop following (no more DMs)" : "Follow with 🔔 (DM me when it changes)"}
              aria-pressed={post.subscribed_by_me} disabled={followPending} onClick={onFollow}
              sx={{ color: post.subscribed_by_me ? "warning.main" : undefined }}>
              {post.subscribed_by_me ? <NotificationsActive /> : <NotificationsOutlined />}
            </IconButton>
          )}
          <IconButton aria-label={`Hide ${title}`} disabled={!canManage || post.hidden} onClick={onHide}>
            <DeleteOutlined />
          </IconButton>
          <IconButton aria-label={`More for ${title}`} aria-haspopup="dialog" onClick={onMenu}>
            <MoreHoriz />
          </IconButton>
        </Box>
      </Box>
    </Box>
  );
}

interface Props {
  channelId: string;
  guildId: string | null;
  channelName: string;
  canManage: boolean;
}

/** The bot's posts in the channel, newest first, with 🔔 and 🗑️ as in Discord. */
export function PostsPanel({ channelId, guildId, channelName, canManage }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const compact = useCompact();
  const follow = useFollow();
  const posts = usePosts(channelId, null);
  const [hiding, setHiding] = useState<ChannelPost | null>(null);
  // The post stays while the sheet slides away, so its title does not go blank.
  const [menu, setMenu] = useState<{ post: ChannelPost; open: boolean } | null>(null);
  const hide = useMutation({
    mutationFn: (post: ChannelPost) => api.hide(channelId, post.item_id),
    onSuccess: (result) => {
      notify(result.posts_queued
        ? `Hidden in #${channelName}. ${plural(result.posts_queued, "post is", "posts are")} being removed${result.bot_running ? "" : " when the bot runs next"}.`
        : `Hidden in #${channelName}.`, "success");
      setHiding(null);
      for (const key of [keys.allPosts, keys.hidden(channelId), keys.allChannels, keys.cleanupStatus(channelId)]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
    onError: (error) => notify(errorMessage(error), "error"),
  });

  if (posts.isPending) {
    return <Stack spacing={1}>{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} variant="rounded" height={compact ? 112 : 56} />)}</Stack>;
  }
  if (posts.isError) return <LoadError error={posts.error} what="Posts" onRetry={() => void posts.refetch()} />;
  const items = posts.data.pages.flatMap((page) => page.posts);
  const notifications = posts.data.pages[0]?.notifications ?? false;
  if (!items.length) {
    return <EmptyState title="No posts">The bot has no live posts here. New and changed listings of this channel's searches appear here once they are posted.</EmptyState>;
  }

  // The latest copy of the post, so the sheet shows a 🔔 change made while it was open.
  const picked = menu && (items.find((post) => post.message_id === menu.post.message_id) ?? menu.post);
  const discord = picked ? discordLink(guildId, channelId, picked.message_id) : null;
  const url = picked ? safeUrl(picked.listing.url) : null;
  const actions: SheetAction[] = picked ? [
    ...(discord ? [{ label: "Open in Discord", icon: <ForumOutlined />, href: discord }] : []),
    ...(url ? [{ label: "Open the listing", icon: <OpenInNew />, href: url }] : []),
    ...(notifications ? [{
      label: picked.subscribed_by_me ? "Stop following" : "Follow with 🔔",
      icon: picked.subscribed_by_me ? <NotificationsOffOutlined /> : <NotificationsOutlined />,
      onSelect: () => follow.toggle(picked.item_id, picked.subscribed_by_me),
      disabled: follow.pending === picked.item_id,
    }] : []),
    { label: `Hide in #${channelName}`, icon: <DeleteOutlined />, onSelect: () => setHiding(picked), disabled: !canManage || picked.hidden },
  ] : [];

  return (
    <>
      <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 0.5 }}>
        {items.map((post) => (
          <PostRow key={post.message_id} post={post} guildId={guildId} channelId={channelId} notifications={notifications}
            canManage={canManage} compact={compact} active={menu?.open === true && menu.post.message_id === post.message_id}
            followPending={follow.pending === post.item_id}
            onFollow={() => follow.toggle(post.item_id, post.subscribed_by_me)} onHide={() => setHiding(post)}
            onMenu={() => setMenu({ post, open: true })} />
        ))}
      </Box>
      {posts.hasNextPage && (
        <Button onClick={() => void posts.fetchNextPage()} disabled={posts.isFetchingNextPage} fullWidth={compact} sx={{ mt: 1.5 }}>
          {posts.isFetchingNextPage ? "Loading" : "Show older posts"}
        </Button>
      )}
      <ActionSheet open={menu?.open ?? false} onClose={() => setMenu((current) => current && { ...current, open: false })}
        title={picked?.listing.title ?? ""} actions={actions}>
        {picked && (
          <Box sx={{ display: "flex", gap: 1.5, alignItems: "center", mt: 1 }}>
            <ListingImage src={picked.listing.image_url} size={56} />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" color="textSecondary" sx={figures}>
                {sourceName(picked.listing.source)}, {formatPrice(picked.listing.price)}, posted {formatRelative(picked.posted_at)}
              </Typography>
              {picked.hidden && <Typography variant="caption" component="p" color="warning">Hidden in #{channelName}.</Typography>}
              {picked.queued && <Typography variant="caption" component="p" color="textSecondary">Its post is being removed.</Typography>}
              {picked.subscribers > 0 && (
                <Typography variant="caption" component="p" color="textSecondary">
                  {plural(picked.subscribers, "person gets", "people get")} DMs for this listing. Who they are is not shown.
                </Typography>
              )}
              {!canManage && (
                <Typography variant="caption" component="p" color="textSecondary">You need Manage Channels here to hide listings.</Typography>
              )}
            </Box>
          </Box>
        )}
      </ActionSheet>
      <ConfirmDialog open={hiding !== null} title="Hide this listing here?" confirm="Hide" busy={hide.isPending} danger
        onClose={() => setHiding(null)} onConfirm={() => hiding && hide.mutate(hiding)}>
        <Typography variant="body2">
          This does what 🗑️ does in Discord: the listing is not posted in #{channelName} again, and its posts here are
          removed. People who follow it with 🔔 still get their DMs.
        </Typography>
      </ConfirmDialog>
    </>
  );
}
