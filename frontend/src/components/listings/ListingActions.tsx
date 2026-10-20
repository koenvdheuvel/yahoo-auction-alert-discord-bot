import InfoOutlined from "@mui/icons-material/InfoOutlined";
import LinkOutlined from "@mui/icons-material/LinkOutlined";
import NotificationsActive from "@mui/icons-material/NotificationsActive";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import OpenInNew from "@mui/icons-material/OpenInNew";
import ScienceOutlined from "@mui/icons-material/ScienceOutlined";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { useSession } from "../../api/hooks";
import type { Candidate } from "../../api/types";
import { formatPrice, safeUrl } from "../../lib/format";
import { listingTitle } from "../../lib/listing";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { VerdictText } from "../common/Decision";
import { ListingImage } from "../common/ListingImage";
import { useNotify } from "../common/notify";
import { ActionSheet, type SheetAction } from "../common/Sheet";
import { followLabel, useFollow } from "../common/follow";

interface Props {
  /** The listing whose actions show; null closes the sheet. */
  candidate: Candidate | null;
  onClose: () => void;
  onDetails: () => void;
  onTestTitle: (candidate: Candidate) => void;
}

/** A listing's actions as a sheet, for a long press on the listing. */
export function ListingActions({ candidate, onClose, onDetails, onTestTitle }: Props) {
  const notify = useNotify();
  const follow = useFollow();
  // 🔔 follows a stored listing; listings the bot filtered were never stored.
  const notifications = useSession().data?.features?.notifications ?? false;
  // The sheet keeps showing the listing while it slides away.
  const [shown, setShown] = useState(candidate);
  if (candidate && candidate !== shown) setShown(candidate);
  if (!shown) return null;

  const url = safeUrl(shown.payload.url);
  const itemId = notifications ? shown.item_id : null;
  const following = shown.subscribed ?? false;
  const actions: SheetAction[] = [{ label: "Show details", icon: <InfoOutlined />, onSelect: onDetails }];
  if (url) actions.push({ label: `Open on ${sourceName(shown.source)}`, icon: <OpenInNew />, href: url });
  actions.push({ label: "Test with the draft", icon: <ScienceOutlined />, onSelect: () => onTestTitle(shown) });
  if (itemId) {
    actions.push({ label: followLabel(following), icon: following ? <NotificationsActive /> : <NotificationsOutlined />,
      onSelect: () => follow.toggle(itemId, following), disabled: follow.pending === itemId });
  }
  // Browsers only offer the clipboard on https pages and on this computer's own addresses.
  if (url && "clipboard" in navigator) {
    actions.push({ label: "Copy the listing link", icon: <LinkOutlined />, onSelect: () => {
      navigator.clipboard.writeText(url).then(() => notify("Copied the link."), () => notify("Copying the link failed.", "error"));
    } });
  }

  return (
    <ActionSheet open={candidate !== null} onClose={onClose} title={listingTitle(shown)} actions={actions}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, mt: 1.25 }}>
        <Box sx={{ width: 48, flex: "none", borderRadius: 0.5, overflow: "hidden" }}>
          <ListingImage src={shown.payload.image_url} />
        </Box>
        <Box sx={{ minWidth: 0, display: "grid", gap: 0.25 }}>
          <VerdictText verdict={shown.verdict} />
          <Typography variant="body2" color="textSecondary" noWrap sx={figures}>
            <Box component="span" sx={{ color: "text.primary", fontWeight: 650 }}>{formatPrice(shown.payload.price)}</Box>
            {` · ${sourceName(shown.source)}`}
          </Typography>
        </Box>
      </Box>
    </ActionSheet>
  );
}
