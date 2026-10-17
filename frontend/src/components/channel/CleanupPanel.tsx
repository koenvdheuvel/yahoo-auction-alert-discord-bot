import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../../api/client";
import { keys, useHistoryScan } from "../../api/hooks";
import type { AlertSummary, HistoryScan, Posting, RemovalDays } from "../../api/types";
import { errorMessage } from "../../lib/errors";
import { formatCount, formatPrice, formatRelative, plural } from "../../lib/format";
import { REMOVAL_RANGES } from "../../lib/removal";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { ConfirmDialog, LoadError } from "../common/Feedback";
import { ListingImage } from "../common/ListingImage";
import { useNotify } from "../common/notify";
import { CleanupProgress } from "../removal/RemovalProgress";

const SAMPLE = 5;
const MAX_DELETE_COUNT = 100;

function Section({ title, children, hint }: { title: string; hint: ReactNode; children: ReactNode }) {
  return (
    <Paper component="section" aria-label={title} sx={{ p: 2, bgcolor: "background.paper", mb: 2 }}>
      <Typography variant="h3" component="h2">{title}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>{hint}</Typography>
      {children}
    </Paper>
  );
}

function ScanResult({ scan }: { scan: HistoryScan }) {
  const what = scan.action === "delete_bot_posts" ? `${plural(scan.done, "bot post")} deleted` : `${plural(scan.done, "🗑️ reaction")} added`;
  if (scan.state === "running") {
    return <Alert severity="info" icon={false}><LinearProgress sx={{ mb: 1 }} />Reading the channel's messages: {what} so far.</Alert>;
  }
  if (scan.state === "forbidden") {
    return <Alert severity="warning">Stopped after {what}: the bot needs Read Message History and the permission to delete or react.</Alert>;
  }
  if (scan.state === "failed") return <Alert severity="error">Stopped after {what} because of an error. See the bot logs.</Alert>;
  return <Alert severity="success">Done: {what} in the latest {formatCount(scan.history_limit)} messages.</Alert>;
}

interface Props {
  channelId: string;
  channelName: string;
  searches: AlertSummary[];
  canManage: boolean;
  posting: Posting | null;
}

/** /cleanup and /reacttocleanup, and removing the channel's posts through the bot's queue. */
export function CleanupPanel({ channelId, channelName, searches, canManage, posting }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const [days, setDays] = useState<RemovalDays>(30);
  const [alertId, setAlertId] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [count, setCount] = useState("10");
  const preview = useQuery({
    queryKey: ["cleanup-preview", channelId, days, alertId],
    queryFn: ({ signal }) => api.cleanupPreview(channelId, days, alertId || null, signal),
    staleTime: 0,
    gcTime: 0,
  });
  const remove = useMutation({
    mutationFn: (messageIds: string[]) => api.cleanup(channelId, messageIds),
    onSuccess: (result) => {
      setConfirming(false);
      notify(`${plural(result.queued, "post")} queued for removal${result.bot_running ? "" : "; they go when the bot runs next"}.`, "success");
      for (const key of [keys.cleanupStatus(channelId), keys.allPosts, ["cleanup-preview", channelId]]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
    onError: (error) => notify(errorMessage(error), "error"),
  });
  const scan = useHistoryScan(channelId);
  const startScan = useMutation({
    mutationFn: (action: "delete_bot_posts" | "add_reactions") =>
      api.startScan(channelId, action, action === "delete_bot_posts" ? Number(count) : undefined),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.scan(channelId) }),
    onError: (error) => notify(errorMessage(error), "error"),
  });

  const data = preview.data;
  const twoWeeksBefore = preview.dataUpdatedAt - 14 * 24 * 3600 * 1000;
  const old = data ? data.posts.filter((post) => Date.parse(post.posted_at) < twoWeeksBefore).length : 0;
  const countValue = Number(count);
  const countValid = Number.isInteger(countValue) && countValue >= 1 && countValue <= MAX_DELETE_COUNT;
  const running = scan.data?.scan?.state === "running";
  const scanAvailable = scan.data?.available ?? false;

  return (
    <Box sx={{ maxWidth: 880 }}>
      <CleanupProgress channelId={channelId} />
      <Section title="Remove posts" hint={<>
        Removes the bot's tracked posts in #{channelName} through its queue, newest first: up to 100 per request when they
        are under 14 days old. The listings stay saved, and nothing is hidden, so a later change is posted again. Posts that
        someone follows with 🔔 are kept.
      </>}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mb: 2 }}>
          <TextField select label="Posted" value={days === null ? "all" : String(days)} sx={{ minWidth: 180 }}
            onChange={(event) => setDays(event.target.value === "all" ? null : Number(event.target.value) as RemovalDays)}>
            {REMOVAL_RANGES.map((range) => (
              <MenuItem key={range.label} value={range.days === null ? "all" : String(range.days)}>{range.label}</MenuItem>
            ))}
          </TextField>
          <TextField select label="Posts of" value={alertId} onChange={(event) => setAlertId(event.target.value)} sx={{ minWidth: 240 }}
            slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
            <MenuItem value="">Every search, and removed ones</MenuItem>
            {searches.map((search) => <MenuItem key={search.id} value={search.id}>{search.search_query}</MenuItem>)}
          </TextField>
        </Stack>
        {preview.isPending && <LinearProgress />}
        {preview.isError && <LoadError error={preview.error} what="The posts" onRetry={() => void preview.refetch()} />}
        {data && (
          <>
            <Typography variant="body1" sx={{ fontWeight: 600 }}>
              {data.removable_total
                ? `${plural(data.removable_total, "post")} can be removed, of ${formatCount(data.posts_in_range)} in this range.`
                : `No posts to remove, of ${formatCount(data.posts_in_range)} in this range.`}
            </Typography>
            <Typography variant="body2" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
              {[data.kept.subscribed > 0 && `${plural(data.kept.subscribed, "post is", "posts are")} kept because of 🔔 followers.`,
                data.kept.queued > 0 && `${plural(data.kept.queued, "post is", "posts are")} already being removed.`,
                data.removable_total > data.limit && `One run removes at most ${formatCount(data.limit)}; run it again for the rest.`,
                old > 0 && `${plural(old, "post is", "posts are")} older than 14 days and removed one at a time.`,
                posting && !posting.bulk_delete && "Without Manage Messages, the bot removes every post one at a time.",
              ].filter(Boolean).map((line) => <Box key={String(line)}>{line}</Box>)}
            </Typography>
            {data.posts.length > 0 && (
              <Box component="ul" sx={{ listStyle: "none", p: 0, my: 1.5, display: "grid", gap: 0.5 }}>
                {data.posts.slice(0, SAMPLE).map((post) => (
                  <Box component="li" key={post.message_id} sx={{ display: "grid", gridTemplateColumns: "36px minmax(0, 1fr)", gap: 1.25, alignItems: "center" }}>
                    <ListingImage src={post.image_url} size={36} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" noWrap title={post.title}>{post.title}</Typography>
                      <Typography variant="caption" color="text.secondary" sx={figures}>
                        {sourceName(post.source)}, {formatPrice(post.price)}, posted {formatRelative(post.posted_at)}
                      </Typography>
                    </Box>
                  </Box>
                ))}
                {data.posts.length > SAMPLE && (
                  <Typography component="li" variant="caption" color="text.secondary">and {formatCount(data.posts.length - SAMPLE)} more</Typography>
                )}
              </Box>
            )}
            {!data.bot_running && data.removable_total > 0 && (
              <Alert severity="info" sx={{ my: 1.5 }}>The bot does not run with this dashboard, so the posts are removed when it runs next.</Alert>
            )}
            <Button variant="contained" color="error" disabled={!canManage || !data.posts.length || remove.isPending}
              onClick={() => setConfirming(true)}>
              Remove {plural(Math.min(data.posts.length, data.limit), "post")}
            </Button>
            {!canManage && <Typography variant="caption" color="text.secondary" sx={{ ml: 1.5 }}>You need Manage Channels in this channel.</Typography>}
          </>
        )}
      </Section>
      <Section title="Scan recent messages" hint={<>
        Like /cleanup and /reacttocleanup in Discord: these read the channel's latest 1,000 messages, so they also reach
        the bot's posts that it does not track, such as posts from before the database was converted. Command answers
        are left alone.
      </>}>
        {!scanAvailable && (
          <Alert severity="info" sx={{ mb: 1.5 }}>These need the bot running and connected to Discord, and it is not running with this dashboard.</Alert>
        )}
        {posting && !posting.read_history && scanAvailable && (
          <Alert severity="warning" sx={{ mb: 1.5 }}>The bot needs Read Message History here to read the messages.</Alert>
        )}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { sm: "flex-start" }, mb: 1.5 }}>
          <TextField label="How many" value={count} onChange={(event) => setCount(event.target.value)} sx={{ width: 120 }}
            error={!countValid} helperText={countValid ? "1 to 100" : "Enter 1 to 100"}
            slotProps={{ htmlInput: { inputMode: "numeric" } }} />
          <Button variant="outlined" color="error" disabled={!canManage || !scanAvailable || running || !countValid || startScan.isPending}
            onClick={() => startScan.mutate("delete_bot_posts")} sx={{ mt: { sm: 0.25 } }}>
            Delete the latest bot posts
          </Button>
          <Button variant="outlined" color="inherit" disabled={!canManage || !scanAvailable || running || startScan.isPending}
            onClick={() => startScan.mutate("add_reactions")} sx={{ mt: { sm: 0.25 } }}>
            Add 🗑️ to tracked posts
          </Button>
        </Stack>
        {scan.data?.scan && <ScanResult scan={scan.data.scan} />}
      </Section>
      <ConfirmDialog open={confirming} title={`Remove ${plural(Math.min(data?.posts.length ?? 0, data?.limit ?? 0), "post")}?`}
        confirm="Remove posts" busy={remove.isPending} danger onClose={() => setConfirming(false)}
        onConfirm={() => data && remove.mutate(data.posts.map((post) => post.message_id))}>
        <Typography variant="body2">
          The posts are deleted from #{channelName} and cannot be brought back. The listings stay saved, and a later
          change of one is posted again.
        </Typography>
      </ConfirmDialog>
    </Box>
  );
}
