import NotificationsActive from "@mui/icons-material/NotificationsActive";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";

import { useSubscription } from "../../api/hooks";
import { errorMessage } from "../../lib/errors";
import { useNotify } from "./notify";

interface Props {
  itemId: string;
  following: boolean;
  /** A small icon button instead of a button with words. */
  compact?: boolean;
}

/** What the 🔔 reaction does: DMs when the listing's price, buyout or stock changes. */
export function FollowButton({ itemId, following, compact = false }: Props) {
  const notify = useNotify();
  const subscription = useSubscription();
  const toggle = () => subscription.mutate({ itemId, follow: !following }, {
    onSuccess: () => notify(following ? "You no longer get DMs for this listing." :
      "You get a DM when this listing changes.", "success"),
    onError: (error) => notify(errorMessage(error), "error"),
  });
  const label = following ? "Stop following (no more DMs)" : "Follow with 🔔 (DM me when it changes)";
  if (compact) {
    return (
      <Tooltip title={label}>
        <IconButton size="small" aria-label={label} aria-pressed={following} onClick={toggle} disabled={subscription.isPending}
          sx={{ color: following ? "warning.main" : undefined }}>
          {following ? <NotificationsActive fontSize="small" /> : <NotificationsOutlined fontSize="small" />}
        </IconButton>
      </Tooltip>
    );
  }
  return (
    <Button size="small" variant={following ? "outlined" : "contained"} color={following ? "inherit" : "primary"}
      startIcon={following ? <NotificationsActive /> : <NotificationsOutlined />} aria-pressed={following}
      onClick={toggle} disabled={subscription.isPending}>
      {following ? "Following" : "Follow"}
    </Button>
  );
}
