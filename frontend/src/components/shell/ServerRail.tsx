import Avatar from "@mui/material/Avatar";
import Badge from "@mui/material/Badge";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Divider from "@mui/material/Divider";
import Skeleton from "@mui/material/Skeleton";
import Tooltip from "@mui/material/Tooltip";
import type { ReactNode } from "react";

import type { BotUser, GuildSummary } from "../../api/types";
import { guildProblems } from "../../lib/channels";
import { RAIL_WIDTH } from "../../theme";

const ICON = 48;

function initials(name: string | null, id: string): string {
  if (!name) return `…${id.slice(-2)}`;
  const words = name.split(/\s+/).filter(Boolean);
  return words.slice(0, 3).map((word) => [...word][0]).join("").toUpperCase() || name.slice(0, 2);
}

interface ItemProps {
  label: string;
  selected: boolean;
  onClick: () => void;
  alert?: string;
  /** Shown after the name in the tooltip. */
  note?: string;
  children: ReactNode;
}

/** One round button with Discord's pill on the left: short on hover, tall when selected. */
function RailItem({ label, selected, onClick, alert, note, children }: ItemProps) {
  return (
    <Tooltip title={[label, note && `(${note})`].filter(Boolean).join(" ") + (alert ? `: ${alert}` : "")} placement="right">
      <Box sx={{ position: "relative", width: RAIL_WIDTH, display: "flex", justifyContent: "center", my: 0.5,
        "&:hover .pill": { height: selected ? 40 : 20 }, "&:hover .icon": { borderRadius: "16px" } }}>
        <Box className="pill" sx={{ position: "absolute", left: 0, top: "50%", transform: "translateY(-50%)", width: 4,
          height: selected ? 40 : 0, borderRadius: "0 4px 4px 0", bgcolor: "text.primary",
          transition: "height 120ms ease" }} />
        <ButtonBase aria-label={label} aria-current={selected ? "page" : undefined} onClick={onClick}
          sx={{ borderRadius: "50%" }}>
          <Badge color="error" variant="dot" invisible={!alert} overlap="circular"
            sx={{ "& .MuiBadge-dot": { width: 12, height: 12, borderRadius: "50%", border: 3, borderColor: "surface.rail" } }}
            anchorOrigin={{ vertical: "bottom", horizontal: "right" }}>
            <Box className="icon" sx={{ width: ICON, height: ICON, borderRadius: selected ? "16px" : "50%", overflow: "hidden",
              transition: "border-radius 120ms ease", display: "grid", placeItems: "center" }}>
              {children}
            </Box>
          </Badge>
        </ButtonBase>
      </Box>
    </Tooltip>
  );
}

interface Props {
  guilds: GuildSummary[] | undefined;
  selectedId: string | null;
  home: boolean;
  /** What the round button at the top opens: your notifications, or every search with the access key. */
  homeLabel: string;
  bot: BotUser | null;
  onHome: () => void;
  onSelect: (guildId: string) => void;
}

/** Discord's server list: home at the top, then one round icon per server. */
export function ServerRail({ guilds, selectedId, home, homeLabel, bot, onHome, onSelect }: Props) {
  return (
    <Box component="nav" aria-label="Servers" sx={{ width: RAIL_WIDTH, flex: "none", bgcolor: "surface.rail", py: 1.5,
      overflowY: "auto", scrollbarWidth: "none" }}>
      <RailItem label={homeLabel} selected={home} onClick={onHome}>
        <Avatar src={bot?.avatar_url} alt="" sx={{ width: ICON, height: ICON, bgcolor: "primary.main", borderRadius: 0 }}>
          {bot?.name.slice(0, 1) ?? "D"}
        </Avatar>
      </RailItem>
      <Divider sx={{ width: 32, mx: "auto", my: 1, borderBottomWidth: 2, borderRadius: 1 }} />
      {guilds === undefined && Array.from({ length: 3 }, (_, index) => (
        <Skeleton key={index} variant="circular" width={ICON} height={ICON} sx={{ mx: "auto", my: 1 }} />
      ))}
      {guilds?.map((guild) => {
        const problems = guildProblems(guild);
        return (
          <RailItem key={guild.id} label={guild.name ?? `Server ${guild.id}`} selected={!home && guild.id === selectedId}
            onClick={() => onSelect(guild.id)} alert={problems.join("; ") || undefined}
            note={guild.level === "member" ? "your notifications only" : undefined}>
            <Avatar src={guild.icon_url ?? undefined} alt="" sx={{ width: ICON, height: ICON, borderRadius: 0,
              bgcolor: !home && guild.id === selectedId ? "primary.main" : "background.default",
              color: !home && guild.id === selectedId ? "primary.contrastText" : "text.primary",
              fontSize: "0.9375rem", fontWeight: 600 }}>
              {initials(guild.name, guild.id)}
            </Avatar>
          </RailItem>
        );
      })}
    </Box>
  );
}
