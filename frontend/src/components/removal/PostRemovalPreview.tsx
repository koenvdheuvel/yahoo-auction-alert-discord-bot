import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import type { RemovablePost, RemovalDays, RemovalPreview } from "../../api/types";
import { formatCount, formatPrice, formatRelative, plural, safeUrl } from "../../lib/format";
import { REMOVAL_RANGES, discordLink, reasonLabel } from "../../lib/removal";
import type { PostRemoval } from "../../lib/usePostRemoval";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { LoadError } from "../common/Feedback";
import { ListingImage } from "../common/ListingImage";

const SAMPLE = 5;

function PostRow({ post, preview }: { post: RemovablePost; preview: RemovalPreview }) {
  const discord = discordLink(preview.guild_id, preview.channel_id, post.message_id);
  const listing = safeUrl(post.url);
  return (
    <Box component="li" sx={{ display: "grid", gridTemplateColumns: "40px minmax(0, 1fr) auto", columnGap: 1.25,
      alignItems: "center", py: 0.75 }}>
      <ListingImage src={post.image_url} size={40} />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" noWrap title={post.title}>{post.title}</Typography>
        <Typography variant="caption" color="text.secondary" component="p" sx={figures}>
          {sourceName(post.source)}, {formatPrice(post.price)}, posted {formatRelative(post.posted_at)}
        </Typography>
      </Box>
      <Stack direction="row" spacing={1.25}>
        {discord && <Link href={discord} target="_blank" rel="noopener noreferrer" variant="caption">Discord</Link>}
        {listing && <Link href={listing} target="_blank" rel="noopener noreferrer" variant="caption">Listing</Link>}
      </Stack>
    </Box>
  );
}

function Result({ data, removal }: { data: RemovalPreview; removal: PostRemoval }) {
  const [showAll, setShowAll] = useState(false);
  const posts = data.posts.filter((post) => !removal.kept.has(post.reason));
  const shown = showAll ? posts : posts.slice(0, SAMPLE);
  // Discord's bulk delete only takes posts under 14 days old; older ones cost a request each.
  const twoWeeksBefore = removal.preview.dataUpdatedAt - 14 * 24 * 3600 * 1000;
  const old = posts.filter((post) => Date.parse(post.posted_at) < twoWeeksBefore).length;
  const kept = [
    data.kept.subscribed > 0 && `${plural(data.kept.subscribed, "post has", "posts have")} 🔔 subscribers`,
    data.kept.incomplete > 0 && `${plural(data.kept.incomplete, "post has", "posts have")} incomplete listing facts`,
    data.kept.unchecked > 0 && `${plural(data.kept.unchecked, "post")} could not be checked in time`,
    data.kept.queued > 0 && `${plural(data.kept.queued, "post is", "posts are")} already being removed`,
  ].filter(Boolean);

  return (
    <>
      {data.removable_total === 0 ? (
        <Typography variant="body2">
          {data.days === null ? "None of this search's posts" : `None of the posts from the last ${data.days} days`} need to be removed.
        </Typography>
      ) : (
        <>
          <Typography variant="body2" sx={{ fontWeight: 600, ...figures }}>
            {posts.length ? `${plural(posts.length, "post")} will be removed from Discord.` : "Every reason is unticked, so no posts are removed."}
          </Typography>
          {data.removable_total > data.posts.length && (
            <Typography variant="caption" color="text.secondary" component="p" sx={figures}>
              {formatCount(data.removable_total)} posts match. One run removes the newest {formatCount(data.limit)}; run it
              again afterwards for the rest.
            </Typography>
          )}
          {old > 0 && (
            <Typography variant="caption" color="text.secondary" component="p" sx={figures}>
              {plural(old, "post is", "posts are")} older than 14 days. Discord deletes those one at a time, which can take a while.
            </Typography>
          )}
          <FormGroup aria-label="Why the posts are filtered">
            {data.reasons.map((reason) => (
              <FormControlLabel key={reason.key} sx={{ alignItems: "flex-start", my: 0.25 }}
                control={<Checkbox size="small" checked={!removal.kept.has(reason.key)} onChange={() => removal.toggleReason(reason.key)}
                  sx={{ py: 0.25 }} />}
                label={<Typography variant="body2" sx={{ pt: 0.25, ...figures }}>
                  {reasonLabel(reason.message)} <Box component="span" sx={{ color: "text.secondary" }}>({formatCount(reason.count)})</Box>
                </Typography>} />
            ))}
          </FormGroup>
          {shown.length > 0 && (
            <Box component="ul" aria-label="Posts to remove" sx={{ m: 0, p: 0, listStyle: "none", maxHeight: 280, overflowY: "auto",
              borderTop: 1, borderBottom: 1, borderColor: "divider" }}>
              {shown.map((post) => <PostRow key={post.message_id} post={post} preview={data} />)}
            </Box>
          )}
          {posts.length > SAMPLE && !showAll && (
            <Box><Button size="small" color="inherit" onClick={() => setShowAll(true)}>Show all {formatCount(posts.length)}</Button></Box>
          )}
        </>
      )}
      {kept.length > 0 && (
        <Typography variant="caption" color="text.secondary" component="p" sx={figures}>Kept: {kept.join("; ")}.</Typography>
      )}
      {data.partial && (
        <Typography variant="caption" color="warning.main" component="p" sx={figures}>
          Only {formatCount(data.checked)} of the {formatCount(data.posts_in_range)} posts in this range were checked.
        </Typography>
      )}
      {!data.bot_running && data.removable_total > 0 && (
        <Alert severity="info">The bot does not run with this dashboard, so the posts are removed when it runs next.</Alert>
      )}
    </>
  );
}

/** Which of the search's Discord posts these rules filter, and the choices of which to remove. */
export function PostRemovalPreview({ removal }: { removal: PostRemoval }) {
  const { preview, days } = removal;
  return (
    <Box sx={{ display: "grid", gap: 1.25 }}>
      <TextField select size="small" label="Posts from" value={days === null ? "all" : String(days)} sx={{ maxWidth: 200 }}
        onChange={(event) => removal.setDays(event.target.value === "all" ? null : Number(event.target.value) as RemovalDays)}>
        {REMOVAL_RANGES.map((range) => (
          <MenuItem key={range.label} value={range.days === null ? "all" : String(range.days)}>{range.label}</MenuItem>
        ))}
      </TextField>
      {preview.isFetching && (
        <Box>
          <LinearProgress aria-label="Checking the posts" />
          <Typography variant="caption" color="text.secondary">Checking the posts against the rules</Typography>
        </Box>
      )}
      {preview.isError && !preview.isFetching && (
        <LoadError error={preview.error} what="The posts" onRetry={() => void preview.refetch()} />
      )}
      {preview.data && !preview.isFetching && <Result data={preview.data} removal={removal} />}
      <Typography variant="caption" color="text.secondary" component="p">
        Removed posts cannot be brought back. Posts with 🔔 subscribers stay. The listings in the dashboard stay too.
      </Typography>
    </Box>
  );
}
