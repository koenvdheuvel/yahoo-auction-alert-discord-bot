import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import ListSubheader from "@mui/material/ListSubheader";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { refreshSearches } from "../../api/hooks";
import type { AlertSummary, ChannelList } from "../../api/types";
import { allChannels, postableChannels } from "../../lib/channels";
import { errorMessage } from "../../lib/errors";
import { plural } from "../../lib/format";
import { usePhone } from "../../lib/responsive";
import { useNotify } from "../common/notify";
import { SheetDialog } from "../common/Sheet";
import { ChannelIcon } from "../shell/ChannelIcon";

/** The longest query /register takes; the server checks it the same way. */
export const SEARCH_QUERY_MAX_LENGTH = 100;

interface Props {
  open: boolean;
  channels: ChannelList | undefined;
  /** Picked when the dialog opens from a channel. */
  channelId: string | null;
  onClose: () => void;
  onCreated: (alert: AlertSummary) => void;
}

/** /register: a search query and the channel its listings are posted in. */
export function AddSearchDialog({ open, channels, channelId, onClose, onCreated }: Props) {
  const client = useQueryClient();
  const notify = useNotify();
  const phone = usePhone();
  const postable = postableChannels(channels);
  const [picked, setPicked] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const channel = picked ?? (channelId && postable.some((item) => item.id === channelId) ? channelId : postable[0]?.id ?? "");
  const register = useMutation({
    mutationFn: () => api.register(channel, query),
    onSuccess: (alert) => {
      refreshSearches(client);
      notify(`Registered a search for ${alert.search_query}. Its first listings come with the next check.`, "success");
      setQuery("");
      setPicked(null);
      onCreated(alert);
    },
  });
  const leftOut = allChannels(channels).filter((item) => ["text", "announcement", "thread", "private_thread"].includes(item.kind)).length
    - postable.length;
  const trimmed = query.trim();
  const close = () => {
    register.reset();
    onClose();
  };

  // Channels grouped under their category, as in the channel list.
  const groups = (channels?.sections ?? []).map((section) => ({
    category: section.category,
    items: section.channels.flatMap((row) => [row, ...(row.threads ?? [])])
      .filter((row) => postable.some((item) => item.id === row.id))
      .map((row) => ({ row, thread: row.parent_id !== null && section.channels.every((item) => item.id !== row.id) })),
  })).filter((group) => group.items.length > 0);
  // On phones the select opens the phone's own picker instead of a menu over the sheet. That picker shows
  // text only, so channels get a # and threads an arrow.
  const options = phone ? groups.map(({ category, items }) => {
    const choices = items.map(({ row, thread }) => <option key={row.id} value={row.id}>{thread ? `↳ ${row.name}` : `# ${row.name}`}</option>);
    return category ? <optgroup key={category.id} label={category.name}>{choices}</optgroup> : choices;
  }) : groups.flatMap(({ category, items }) => [
    category ? <ListSubheader key={`category-${category.id}`}>{category.name}</ListSubheader> : null,
    ...items.map(({ row, thread }) => (
      <MenuItem key={row.id} value={row.id} sx={{ gap: 1, pl: thread ? 4 : 2 }}>
        <ChannelIcon kind={row.kind} sx={{ color: "text.secondary" }} />
        {row.name}
      </MenuItem>
    )),
  ]);

  return (
    <SheetDialog open={open} onClose={register.isPending ? undefined : close} maxWidth="sm" aria-labelledby="add-search-title">
      {/* The form passes the sheet's height on to its parts, so the content scrolls and the buttons stay in view. */}
      <Box component="form" onSubmit={(event) => { event.preventDefault(); register.mutate(); }}
        sx={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        <DialogTitle id="add-search-title">Add a search</DialogTitle>
        <DialogContent sx={{ display: "grid", gap: 2, pt: "8px !important" }}>
          <Typography variant="body2" color="textSecondary">
            Like /register in Discord: the bot checks the marketplaces for this query and posts new and changed listings
            in the channel, with 🗑️ and 🔔 under each post.
          </Typography>
          {postable.length === 0 ? (
            <Alert severity="info">
              There is no channel here where the bot can post and you can change channels. The channel list marks
              channels where the bot lacks a permission.
            </Alert>
          ) : (
            <TextField select label="Channel" value={channel} onChange={(event) => setPicked(event.target.value)} required
              slotProps={{ select: { native: phone } }}>
              {options}
            </TextField>
          )}
          <TextField label="Search query" value={query} onChange={(event) => setQuery(event.target.value)} required autoFocus
            slotProps={{ htmlInput: { maxLength: SEARCH_QUERY_MAX_LENGTH } }}
            helperText={`${query.length} of ${SEARCH_QUERY_MAX_LENGTH} characters. Spaces at the ends are dropped.`} />
          {leftOut > 0 && (
            <Typography variant="caption" color="textSecondary">
              {plural(leftOut, "channel")} left out: the bot cannot post there, or you lack Manage Channels.
            </Typography>
          )}
          {register.isError && <Alert severity="error">{errorMessage(register.error)}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={close} color="inherit" disabled={register.isPending}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={!trimmed || !channel || register.isPending}>
            {register.isPending ? "Adding" : "Add search"}
          </Button>
        </DialogActions>
      </Box>
    </SheetDialog>
  );
}
