import Add from "@mui/icons-material/Add";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Skeleton from "@mui/material/Skeleton";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { AlertSummary, ChannelList } from "../../api/types";
import { findChannel, postingProblem } from "../../lib/channels";
import type { ChannelTab, Place } from "../../lib/hooks";
import { TOPBAR_HEIGHT } from "../../theme";
import { EmptyState } from "../common/Feedback";
import { CleanupPanel } from "../channel/CleanupPanel";
import { HiddenPanel } from "../channel/HiddenPanel";
import { PostsPanel } from "../channel/PostsPanel";
import { SearchList } from "../searches/SearchList";

const TABS: Record<ChannelTab, string> = { searches: "Searches", posts: "Posts", hidden: "Hidden", cleanup: "Cleanup" };

interface Props {
  channelId: string;
  guildId: string | null;
  channels: ChannelList | undefined;
  searches: AlertSummary[];
  place: Place;
  navigate: (next: Partial<Place>) => void;
  onAddSearch: () => void;
  onUnregister: (alert: AlertSummary) => void;
}

/** One channel: its searches, the bot's posts, hidden listings and cleanup. */
export function ChannelView({ channelId, guildId, channels, searches, place, navigate, onAddSearch, onUnregister }: Props) {
  const channel = findChannel(channels, channelId);
  const unknown = channels?.unknown.find((item) => item.id === channelId) ?? null;
  if (!channels) return <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={120} /></Box>;
  if (!channel && !unknown) {
    return (
      <Box sx={{ p: 3 }}>
        <EmptyState title="Channel not found">It is not in this server's channel list, or the bot cannot see it.</EmptyState>
      </Box>
    );
  }
  const canManage = channel?.can_manage ?? false;
  // A channel that is gone, or that Discord does not show the bot, has no posts to look at.
  const tabs: ChannelTab[] = channel ? ["searches", "posts", "hidden", "cleanup"] : ["searches", "hidden"];
  const tab = tabs.includes(place.channelTab) ? place.channelTab : "searches";
  const problem = channel ? postingProblem(channel) : null;
  const name = channel?.name ?? channelId;

  return (
    <>
      <Box sx={{ px: { xs: 2, md: 3 }, pt: 2 }}>
        {unknown && (
          <Alert severity={unknown.deleted ? "error" : "warning"} sx={{ mb: 2 }}>
            {unknown.deleted
              ? "Discord says this channel was deleted. Unregister its searches here; hidden listings can be cleared too."
              : channels.source === "none"
                ? "The dashboard has no bot token, so it knows this channel only by its ID."
                : "Discord does not show this channel to the bot. Give the bot View Channel there, or unregister its searches in Discord."}
          </Alert>
        )}
        {channel && problem && (
          <Alert severity={searches.length ? "error" : "warning"} sx={{ mb: 2 }}>
            {problem} {searches.length ? "Its searches cannot post until that is fixed." : "Searches cannot be added here until then."}
          </Alert>
        )}
        {channel && !canManage && (
          <Alert severity="info" sx={{ mb: 2 }}>
            You do not have Manage Channels in #{channel.name}, so you can look but not change anything here.
          </Alert>
        )}
      </Box>
      <Box sx={{ px: { xs: 2, md: 3 }, borderBottom: 1, borderColor: "divider", position: "sticky", top: TOPBAR_HEIGHT,
        bgcolor: "background.default", zIndex: 3 }}>
        <Tabs value={tab} onChange={(_, next: ChannelTab) => navigate({ channelTab: next })} aria-label="Channel sections"
          variant="scrollable" allowScrollButtonsMobile>
          {tabs.map((value) => <Tab key={value} value={value} label={TABS[value]} id={`channel-tab-${value}`} aria-controls="channel-panel" />)}
        </Tabs>
      </Box>
      <Box id="channel-panel" role="tabpanel" aria-labelledby={`channel-tab-${tab}`} sx={{ px: { xs: 2, md: 3 }, py: 2.5 }}>
        {tab === "searches" && (
          <>
            <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 1.5, flexWrap: "wrap" }}>
              <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 240 }}>
                What /alerts lists in this channel. Each search posts its new and changed listings here.
              </Typography>
              {channel && (
                <Tooltip title={!canManage ? "You need Manage Channels in this channel" : problem ?? ""}>
                  <span>
                    <Button variant="contained" startIcon={<Add />} onClick={onAddSearch}
                      disabled={!canManage || !channel.posting.can_post}>Add search</Button>
                  </span>
                </Tooltip>
              )}
            </Box>
            {searches.length ? (
              <SearchList alerts={searches} canChange={() => canManage || Boolean(unknown?.deleted)}
                onOpen={(alert) => navigate({ alertId: alert.id })} onUnregister={onUnregister} />
            ) : (
              <EmptyState title="No searches here">Add one, or run /register in this channel.</EmptyState>
            )}
          </>
        )}
        {tab === "posts" && channel && <PostsPanel channelId={channelId} guildId={guildId} channelName={name} canManage={canManage} />}
        {tab === "hidden" && <HiddenPanel channelId={channelId} canChange={canManage || Boolean(unknown?.deleted)} />}
        {tab === "cleanup" && channel && (
          <CleanupPanel channelId={channelId} channelName={name} searches={searches} canManage={canManage} posting={channel.posting} />
        )}
      </Box>
    </>
  );
}
