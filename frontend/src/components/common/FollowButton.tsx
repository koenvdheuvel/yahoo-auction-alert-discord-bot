import NotificationsActive from "@mui/icons-material/NotificationsActive";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";

import { followLabel, useFollow } from "./follow";

interface Props {
  itemId: string;
  following: boolean;
  /** A small icon button instead of a button with words. */
  compact?: boolean;
}

/** What the 🔔 reaction does: DMs when the listing's price, buyout or stock changes. */
export function FollowButton({ itemId, following, compact = false }: Props) {
  const follow = useFollow();
  const toggle = () => follow.toggle(itemId, following);
  const label = followLabel(following);
  if (compact) {
    return (
      <Tooltip title={label}>
        <IconButton size="small" aria-label={label} aria-pressed={following} onClick={toggle} disabled={follow.pending === itemId}
          sx={{ color: following ? "warning.main" : undefined }}>
          {following ? <NotificationsActive fontSize="small" /> : <NotificationsOutlined fontSize="small" />}
        </IconButton>
      </Tooltip>
    );
  }
  return (
    <Button size="small" variant={following ? "outlined" : "contained"} color={following ? "inherit" : "primary"}
      startIcon={following ? <NotificationsActive /> : <NotificationsOutlined />} aria-pressed={following}
      onClick={toggle} disabled={follow.pending === itemId}>
      {following ? "Following" : "Follow"}
    </Button>
  );
}
