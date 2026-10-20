import Add from "@mui/icons-material/Add";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";

import type { AlertSummary, ChannelList } from "../../api/types";
import { canChangeSearch, postableChannels } from "../../lib/channels";
import { EmptyState } from "../common/Feedback";
import { SearchList } from "../searches/SearchList";

interface Props {
  searches: AlertSummary[];
  channels: ChannelList | undefined;
  onOpen: (alert: AlertSummary) => void;
  onOpenChannel: (channelId: string) => void;
  onAdd: () => void;
  onUnregister: (alert: AlertSummary) => void;
}

/** The server's searches in every channel, as /allalerts lists them. */
export function SearchesView({ searches, channels, onOpen, onOpenChannel, onAdd, onUnregister }: Props) {
  const sorted = [...searches].sort((left, right) =>
    (left.channel_name ?? left.channel_id).localeCompare(right.channel_name ?? right.channel_id)
    || left.search_query.localeCompare(right.search_query));
  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 1.5, flexWrap: "wrap" }}>
        <Typography variant="body2" color="textSecondary" sx={{ flex: 1, minWidth: 240 }}>
          Every search in this server, as /allalerts lists them. Open a channel for its posts, hidden listings and cleanup.
        </Typography>
        <Button variant="contained" startIcon={<Add />} onClick={onAdd} disabled={postableChannels(channels).length === 0}>
          Add search
        </Button>
      </Box>
      {sorted.length ? (
        <SearchList alerts={sorted} showChannel canChange={(alert) => canChangeSearch(channels, alert)}
          onOpen={onOpen} onOpenChannel={onOpenChannel} onUnregister={onUnregister} />
      ) : (
        <EmptyState title="No searches yet">Add one here, or run /register in a channel.</EmptyState>
      )}
    </Box>
  );
}

interface EveryProps {
  searches: AlertSummary[];
  guildName: (guildId: string | null) => string;
  onOpen: (alert: AlertSummary) => void;
}

/** With the access key: every server's searches, including any whose server is not known yet. */
export function EverySearchView({ searches, guildName, onOpen }: EveryProps) {
  const byGuild = new Map<string, AlertSummary[]>();
  for (const alert of searches) {
    const key = alert.guild_id ?? "";
    byGuild.set(key, [...(byGuild.get(key) ?? []), alert]);
  }
  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
      {searches.length === 0 && <EmptyState title="No searches yet">Run /register in a Discord channel to add one.</EmptyState>}
      {[...byGuild.entries()].map(([guildId, alerts]) => (
        <Box key={guildId} component="section" sx={{ mb: 3 }}>
          <Typography variant="h3" component="h2" sx={{ mb: 1 }}>{guildName(guildId || null)}</Typography>
          <SearchList alerts={alerts} showChannel canChange={() => false} onOpen={onOpen} />
        </Box>
      ))}
    </Box>
  );
}
