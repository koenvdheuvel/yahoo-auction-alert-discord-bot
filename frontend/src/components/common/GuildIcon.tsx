import Avatar from "@mui/material/Avatar";

import type { Guild } from "../../api/types";

/** A Discord server's icon, or its first letter when it has none. */
export function GuildIcon({ guild, size = 22 }: { guild: Guild; size?: number }) {
  return (
    <Avatar variant="rounded" src={guild.icon_url ?? undefined} alt=""
      sx={{ width: size, height: size, fontSize: size * 0.5, fontWeight: 650, bgcolor: "text.secondary" }}>
      {guild.name.slice(0, 1).toUpperCase()}
    </Avatar>
  );
}
