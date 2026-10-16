import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
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
import { discordLink } from "../../lib/removal";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { ConfirmDialog, EmptyState, LoadError } from "../common/Feedback";
import { FollowButton } from "../common/FollowButton";
import { ListingImage } from "../common/ListingImage";
import { useNotify } from "../common/notify";

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
  const posts = usePosts(channelId, null);
  const [hiding, setHiding] = useState<ChannelPost | null>(null);
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

  if (posts.isPending) return <Stack spacing={1}>{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} variant="rounded" height={56} />)}</Stack>;
  if (posts.isError) return <LoadError error={posts.error} what="Posts" onRetry={() => void posts.refetch()} />;
  const items = posts.data.pages.flatMap((page) => page.posts);
  const notifications = posts.data.pages[0]?.notifications ?? false;
  if (!items.length) {
    return <EmptyState title="No posts">The bot has no live posts here. New and changed listings of this channel's searches appear here once they are posted.</EmptyState>;
  }
  return (
    <>
      <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 0.5 }}>
        {items.map((post) => {
          const discord = discordLink(guildId, channelId, post.message_id);
          const url = safeUrl(post.listing.url);
          return (
            <Box component="li" key={post.message_id} sx={{ display: "grid", gridTemplateColumns: "48px minmax(0, 1fr) auto",
              gap: 1.5, alignItems: "center", p: 1, borderRadius: 1, "&:hover": { bgcolor: "surface.hover" } }}>
              <ListingImage src={post.listing.image_url} size={48} />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body1" noWrap title={post.listing.title} sx={{ fontWeight: 600 }}>{post.listing.title}</Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 0.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={figures}>
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
                    <IconButton size="small" aria-label={`Hide ${post.listing.title}`} disabled={!canManage || post.hidden}
                      onClick={() => setHiding(post)}>
                      <DeleteOutlined fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </Stack>
            </Box>
          );
        })}
      </Box>
      {posts.hasNextPage && (
        <Button onClick={() => void posts.fetchNextPage()} disabled={posts.isFetchingNextPage} sx={{ mt: 1.5 }}>
          {posts.isFetchingNextPage ? "Loading" : "Show older posts"}
        </Button>
      )}
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
