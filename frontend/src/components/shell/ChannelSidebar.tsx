import ChevronRight from "@mui/icons-material/ChevronRight";
import CollectionsOutlined from "@mui/icons-material/CollectionsOutlined";
import ExpandMore from "@mui/icons-material/ExpandMore";
import MonitorHeartOutlined from "@mui/icons-material/MonitorHeartOutlined";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import WarningAmber from "@mui/icons-material/WarningAmber";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Skeleton from "@mui/material/Skeleton";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { UseQueryResult } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import type { AlertSummary, ChannelList, ChannelRow, UnknownChannel } from "../../api/types";
import { postingProblem, searchesByChannel } from "../../lib/channels";
import { formatCount } from "../../lib/format";
import type { Place } from "../../lib/hooks";
import { useTouch } from "../../lib/responsive";
import { SIDEBAR_WIDTH, TOPBAR_HEIGHT, figures } from "../../theme";
import { LoadError } from "../common/Feedback";
import { SearchUnread } from "../searches/SearchUnread";
import { ChannelIcon } from "./ChannelIcon";

const COLLAPSED_KEY = "dashboard:collapsed";

function readCollapsed(): Set<string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(COLLAPSED_KEY) ?? "[]") as unknown;
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
}

// On touch screens rows get 44 pixels, the smallest target Apple and Google recommend for a finger.
const TOUCH = "@media (pointer: coarse)";

interface RowProps {
  icon: ReactNode;
  label: string;
  selected: boolean;
  onClick: () => void;
  /** Bright like a channel with unread messages: it has searches, or it is a page of the server. */
  bright?: boolean;
  depth?: number;
  end?: ReactNode;
  title?: string;
  /** A second line, for what a mouse would show on hover. Touch screens have no hover. */
  detail?: { text: string; color: string } | null;
}

/** One line in the channel list, sized and coloured like Discord's. */
function Row({ icon, label, selected, onClick, bright = false, depth = 0, end, title, detail }: RowProps) {
  const name = (
    <Typography component="span" variant="body1" noWrap
      sx={{ flex: 1, minWidth: 0, fontWeight: selected || bright ? 600 : 500, fontSize: depth ? "0.8125rem" : "0.9375rem",
        display: detail ? "block" : undefined }}>
      {label}
    </Typography>
  );
  return (
    <ButtonBase onClick={onClick} aria-current={selected ? "page" : undefined} title={title}
      sx={{ display: "flex", width: "calc(100% - 16px)", mx: 1, my: "1px", pl: 1 + depth * 2, pr: 1, minHeight: 32,
        borderRadius: 1, justifyContent: "flex-start", gap: 0.75, textAlign: "left",
        color: selected || bright ? "text.primary" : "surface.muted",
        bgcolor: selected ? "surface.selected" : "transparent",
        [TOUCH]: { minHeight: 44 },
        // A tap leaves no hover behind on a phone; the row lights up while the finger is on it instead.
        "@media (hover: hover)": { "&:hover": { bgcolor: selected ? "surface.selected" : "surface.hover", color: "text.primary" } },
        "@media (hover: none)": { "&:active": { bgcolor: selected ? "surface.selected" : "surface.hover" } } }}>
      <Box component="span" sx={{ display: "flex", color: selected || bright ? "text.secondary" : "surface.muted" }}>{icon}</Box>
      {detail ? (
        <Box component="span" sx={{ flex: 1, minWidth: 0, py: 0.5 }}>
          {name}
          {/* Up to two lines, so a reason such as a missing permission is not cut off. */}
          <Typography component="span" variant="caption" sx={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
            overflow: "hidden", color: detail.color }}>{detail.text}</Typography>
        </Box>
      ) : name}
      {end}
    </ButtonBase>
  );
}

function CountBadge({ value, label }: { value: number; label: string }) {
  return (
    <Box component="span" aria-label={label} title={label}
      sx={{ minWidth: 16, height: 16, px: 0.5, borderRadius: 8, bgcolor: "primary.main", color: "primary.contrastText",
        fontSize: "0.6875rem", fontWeight: 700, display: "grid", placeItems: "center", ...figures }}>
      {formatCount(value)}
    </Box>
  );
}

/** Why the bot cannot post in a channel where searches can go, or null when it can. */
function warning(channel: ChannelRow): string | null {
  return ["text", "announcement", "thread", "private_thread"].includes(channel.kind) ? postingProblem(channel) : null;
}

/** What the warning icon and the archived mark show on hover, as a line under the name for touch screens. */
function channelDetail(channel: ChannelRow): RowProps["detail"] {
  const problem = warning(channel);
  if (problem) return { text: problem, color: channel.searches ? "error.main" : "warning.main" };
  return channel.archived ? { text: "Archived thread", color: "surface.muted" } : null;
}

function PostingWarning({ channel, described }: { channel: ChannelRow; described: boolean }) {
  const problem = warning(channel);
  if (!problem) return null;
  const sx = { fontSize: 16, color: channel.searches ? "error.main" : "warning.main" };
  // When the reason is written under the name, the icon only marks the row.
  if (described) return <WarningAmber sx={sx} />;
  return (
    <Tooltip title={problem}>
      <WarningAmber role="img" aria-hidden={false} aria-label={problem} sx={sx} />
    </Tooltip>
  );
}

interface Props {
  guildName: string | null;
  channels: UseQueryResult<ChannelList> | null;
  alerts: AlertSummary[] | undefined;
  guildId: string | null;
  place: Place;
  onNavigate: (next: Partial<Place>) => void;
  /** Home: your notifications with Discord sign-in, or every search with the access key. */
  home: { label: string; notifications: boolean } | null;
  /** A server where you are only a member: just your notifications there. */
  member?: boolean;
  footer: ReactNode;
}

/** The channel list of the picked server, as Discord shows it, with each channel's searches under it. */
export function ChannelSidebar({ guildName, channels, alerts, guildId, place, onNavigate, home, member = false, footer }: Props) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [finder, setFinder] = useState({ guildId, text: "" });
  const find = finder.guildId === guildId ? finder.text : "";
  const needle = find.trim().toLocaleLowerCase();
  const touch = useTouch();
  const byChannel = searchesByChannel(alerts, guildId);
  const searchCount = [...byChannel.values()].reduce((total, list) => total + list.length, 0);
  const atServer = !place.me && !place.alertId && !place.channelId;
  const selectedChannel = place.channelId ?? alerts?.find((alert) => alert.id === place.alertId)?.channel_id;
  const matches = (text: string) => text.toLocaleLowerCase().includes(needle);
  const matchesChannel = (channel: ChannelRow): boolean => !needle || matches(channel.name)
    || (byChannel.get(channel.id) ?? []).some((alert) => matches(alert.search_query)) || (channel.threads ?? []).some(matchesChannel);
  const sections = channels?.data?.sections.map((section) => ({ ...section, channels: section.channels.filter(matchesChannel) }))
    .filter((section) => section.channels.length > 0);
  const unknown = channels?.data?.unknown.filter((channel) => !needle || matches(channel.id)
    || (byChannel.get(channel.id) ?? []).some((alert) => matches(alert.search_query))) ?? [];

  const toggle = (categoryId: string) => {
    const next = new Set(collapsed);
    if (next.has(categoryId)) next.delete(categoryId);
    else next.add(categoryId);
    setCollapsed(next);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
    } catch {
      // Storage blocked: the categories open again on reload.
    }
  };

  const searchRows = (channelId: string, depth: number, showAll = false) => (byChannel.get(channelId) ?? [])
    .filter((alert) => !needle || showAll || matches(alert.search_query))
    .map((alert) => (
      <Row key={alert.id} depth={depth} icon={<SearchOutlined sx={{ fontSize: 16 }} />} label={alert.search_query}
        title={alert.search_query} selected={place.alertId === alert.id} bright
        onClick={() => onNavigate({ alertId: alert.id, channelId: null, me: false })}
        end={<>
          <SearchUnread alertId={alert.id} />
          {alert.review_count ? <CountBadge value={alert.review_count} label={`${formatCount(alert.review_count)} need review`} /> : null}
        </>} />
    ));

  const channelRow = (channel: ChannelRow, depth = 0): ReactNode => matchesChannel(channel) && (
    <Box key={channel.id}>
      <Row depth={depth} icon={<ChannelIcon kind={channel.kind} />} label={channel.name}
        title={channel.archived ? `${channel.name} (archived)` : channel.name} detail={touch ? channelDetail(channel) : null}
        selected={place.channelId === channel.id && !place.alertId} bright={channel.searches > 0 || channel.hidden > 0}
        onClick={() => onNavigate({ channelId: channel.id, alertId: null, me: false })}
        end={<>
          <PostingWarning channel={channel} described={touch} />
          {channel.searches > 0 && <CountBadge value={channel.searches}
            label={`${formatCount(channel.searches)} ${channel.searches === 1 ? "search" : "searches"}`} />}
        </>} />
      {searchRows(channel.id, depth + 1, matches(channel.name))}
      {/* Threads without searches or hidden listings stay out of the way, unless one is open. */}
      {channel.threads?.filter((thread) => thread.searches || thread.hidden || thread.id === selectedChannel || Boolean(needle))
        .map((thread) => channelRow(thread, depth + 1))}
    </Box>
  );

  const unknownRow = (channel: UnknownChannel) => (
    <Box key={channel.id}>
      <Row icon={<ChannelIcon kind="text" />} label={`…${channel.id.slice(-6)}`} bright
        title={`Channel ${channel.id}: ${channel.deleted ? "Discord says it was deleted." : "Discord does not show it to the bot."}`}
        selected={place.channelId === channel.id && !place.alertId}
        onClick={() => onNavigate({ channelId: channel.id, alertId: null, me: false })}
        end={<Typography component="span" variant="caption" sx={{ color: channel.deleted ? "error.main" : "surface.muted" }}>
          {channel.deleted ? "deleted" : "unknown"}
        </Typography>} />
      {searchRows(channel.id, 1)}
    </Box>
  );

  return (
    // The list gives up width before the server list does when the drawer is narrower than both, on small phones.
    <Box sx={{ width: SIDEBAR_WIDTH, flex: "0 1 auto", minWidth: 0, bgcolor: "surface.sidebar", display: "flex",
      flexDirection: "column", minHeight: 0, height: "100%" }}>
      <Box component="header" sx={{ height: TOPBAR_HEIGHT, flex: "none", px: 2, display: "flex", alignItems: "center",
        boxShadow: "0 1px 0 rgba(0,0,0,0.2)", zIndex: 1 }}>
        <Typography variant="h2" component="h2" noWrap>{home ? home.label : guildName ?? "Server"}</Typography>
      </Box>
      {!member && !home && (
        <Box sx={{ px: 1.5, pt: 1.5 }}>
          <TextField size="small" type="search" label="Find channel or search" value={find} fullWidth
            onChange={(event) => setFinder({ guildId, text: event.target.value })} />
        </Box>
      )}
      <Box component="nav" aria-label={home ? home.label : "Channels"} sx={{ flex: 1, overflowY: "auto", py: 1.5,
        scrollbarWidth: "thin" }}>
        {member ? (
          <>
            <Row icon={<NotificationsOutlined sx={{ fontSize: 18 }} />} label="Your notifications" bright selected
              onClick={() => onNavigate({ me: false })} />
            <Typography variant="caption" component="p" color="textSecondary" sx={{ px: 2, pt: 1.5 }}>
              You are a member here, so you manage your own 🔔 notifications. People with Manage Channels in this
              server also see its channels and searches.
            </Typography>
          </>
        ) : home ? (
          // Home has one page, and it is open whenever home is: also at the start, before the address says so.
          home.notifications ? (
            <Row icon={<NotificationsOutlined sx={{ fontSize: 18 }} />} label="Your notifications" bright selected
              onClick={() => onNavigate({ me: true })} />
          ) : (
            <Row icon={<SearchOutlined sx={{ fontSize: 18 }} />} label="Every server's searches" bright selected
              onClick={() => onNavigate({ me: true })} />
          )
        ) : (
          <>
            <Row icon={<MonitorHeartOutlined sx={{ fontSize: 18 }} />} label="Status" bright
              selected={atServer && place.view === "status"} onClick={() => onNavigate({ view: "status", channelId: null, alertId: null, me: false })} />
            <Row icon={<SearchOutlined sx={{ fontSize: 18 }} />} label="Searches" bright
              selected={atServer && place.view === "searches"}
              onClick={() => onNavigate({ view: "searches", channelId: null, alertId: null, me: false })}
              end={searchCount ? <Typography component="span" variant="caption" color="textSecondary" sx={figures}>{formatCount(searchCount)}</Typography> : undefined} />
            <Row icon={<CollectionsOutlined sx={{ fontSize: 18 }} />} label="All listings" bright
              selected={atServer && place.view === "listings"}
              onClick={() => onNavigate({ view: "listings", channelId: null, alertId: null, me: false })} />
            {channels?.isPending && Array.from({ length: 6 }, (_, index) => (
              <Skeleton key={index} variant="text" sx={{ mx: 2, my: 0.75 }} />
            ))}
            {channels?.isError && (
              <Box sx={{ p: 1.5 }}><LoadError error={channels.error} what="Channels" onRetry={() => void channels.refetch()} /></Box>
            )}
            {channels?.data?.discord_unavailable && (
              <Alert severity="warning" sx={{ m: 1.5 }}>Discord did not answer, so channels are shown by ID.</Alert>
            )}
            {sections?.map((section) => {
              const key = section.category?.id ?? "none";
              const closed = !needle && section.category !== null && collapsed.has(key);
              return (
                <Box key={key} component="section" aria-label={section.category?.name ?? "Channels without a category"}
                  sx={{ mt: section.category ? 2 : 1, [TOUCH]: { mt: section.category ? 0.5 : 1 } }}>
                  {section.category && (
                    // On touch screens the header is as tall as a row, with its name at the bottom as in Discord.
                    <ButtonBase onClick={() => toggle(key)} aria-expanded={!closed}
                      sx={{ display: "flex", width: "100%", px: 0.5, py: 0.25, justifyContent: "flex-start",
                        color: "surface.muted", [TOUCH]: { minHeight: 44, alignItems: "flex-end", pb: 0.75 },
                        "@media (hover: hover)": { "&:hover": { color: "text.primary" } } }}>
                      {closed ? <ChevronRight sx={{ fontSize: 14 }} /> : <ExpandMore sx={{ fontSize: 14 }} />}
                      <Typography component="span" variant="overline" noWrap sx={{ textTransform: "uppercase" }}>
                        {section.category.name}
                      </Typography>
                    </ButtonBase>
                  )}
                  {closed
                    // A closed category still shows the selected channel, as Discord does.
                    ? section.channels.filter((channel) => selectedChannel === channel.id ||
                      (channel.threads ?? []).some((thread) => thread.id === selectedChannel)).map((channel) => channelRow(channel))
                    : section.channels.map((channel) => channelRow(channel))}
                </Box>
              );
            })}
            {unknown.length > 0 && (
              <Box component="section" aria-label="Unknown channels" sx={{ mt: 2 }}>
                <Typography variant="overline" component="p" sx={{ px: 2, color: "surface.muted", textTransform: "uppercase" }}>
                  {channels?.data?.source === "none" ? "Channels" : "Unknown channels"}
                </Typography>
                {unknown.map(unknownRow)}
              </Box>
            )}
            {needle && channels?.isSuccess && !sections?.length && !unknown.length && (
              <Typography variant="body2" color="textSecondary" sx={{ px: 2, py: 2 }}>No channels or searches match.</Typography>
            )}
          </>
        )}
      </Box>
      {footer}
    </Box>
  );
}

