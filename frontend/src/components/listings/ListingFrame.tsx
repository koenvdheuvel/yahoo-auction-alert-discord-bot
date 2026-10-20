import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { memo, type MouseEvent } from "react";

import type { Candidate } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatDateTime, formatPrice, formatRelative, safeUrl } from "../../lib/format";
import { longPressable, useLongPress } from "../../lib/gestures";
import { listingTitle, surprisingNormalization } from "../../lib/listing";
import { sourceName, VERDICTS } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { DecisionButton } from "../common/Decision";
import { ListingImage } from "../common/ListingImage";
import type { View } from "./FilterBar";

interface Props {
  candidate: Candidate;
  index: number;
  layout: View;
  /** The frame that keyboard focus returns to; only its controls are in the tab order. */
  active: boolean;
  /** Narrow screens: a row puts the decision, price and marketplace under the title. */
  compact: boolean;
  /** Touch screens: a tap anywhere on the listing shows its details, so a stray tap does not leave the dashboard. */
  touch: boolean;
  /** Name the search and channel the listing belongs to; not needed where every listing is one search's. */
  owner: boolean;
  onActivate: (index: number) => void;
  onOpen: (index: number) => void;
  /** A long press: the listing's actions. */
  onMenu: (index: number) => void;
}

/** Where a listing was saved: its search, which may have been unregistered since, and its channel. */
function ownership(candidate: Candidate) {
  const channel = channelLabel(candidate.channel_id, candidate.channel_name);
  const registered = candidate.alert_id !== null;
  return {
    search: `Search: ${candidate.search_query}`,
    channel: registered ? channel : `Unregistered search · ${channel}`,
    spoken: `Search ${candidate.search_query}${registered ? "" : " (unregistered)"} in ${channel}.`,
  };
}

/** The search on one line and the channel under it, so a long search text never hides the channel. */
function Owner({ candidate }: { candidate: Candidate }) {
  const { search, channel } = ownership(candidate);
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="textSecondary" component="p" noWrap title={search}>{search}</Typography>
      <Typography variant="caption" color="textSecondary" component="p" noWrap title={channel}>{channel}</Typography>
    </Box>
  );
}

function Seen({ candidate }: { candidate: Candidate }) {
  const detail = `First seen with this decision ${formatDateTime(candidate.observed_at)}. Last seen ${formatDateTime(candidate.last_seen_at)}.`;
  return (
    <Tooltip title={detail}>
      <Typography variant="caption" color="textSecondary" sx={{ ...figures, whiteSpace: "nowrap" }}>
        {formatRelative(candidate.observed_at)}
      </Typography>
    </Tooltip>
  );
}

// The decision's reasons open in a sheet or popover outside the frame on the page. Their clicks
// still reach the frame through React, so the frame only answers the ones that start inside it.
function inside(event: MouseEvent): boolean {
  return event.target instanceof Node && event.currentTarget.contains(event.target);
}

const clamp = { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", overflowWrap: "anywhere" } as const;

export const ListingFrame = memo(function ListingFrame(props: Props) {
  const { candidate, index, layout, active, compact, touch, owner, onActivate, onOpen, onMenu } = props;
  const title = listingTitle(candidate);
  const url = safeUrl(candidate.payload.url);
  const normalized = surprisingNormalization(candidate);
  const tab = active ? 0 : -1;
  const summary = `${title}. ${VERDICTS[candidate.verdict]}.${owner ? ` ${ownership(candidate).spoken}` : ""}`;
  const press = useLongPress(() => onMenu(index));

  const titleText = url && !touch ? (
    <Link href={url} target="_blank" rel="noopener noreferrer" tabIndex={tab}>{title}</Link>
  ) : title;

  const handlers = {
    ...press,
    // Buttons inside the frame, such as the decision, keep their own taps.
    onClick: touch ? (event: MouseEvent) => {
      if (inside(event) && !(event.target as Element).closest("button, a")) onOpen(index);
    } : undefined,
  };

  const frame = {
    listStyle: "none",
    position: "relative",
    bgcolor: "background.paper",
    outline: "none",
    "&:focus-visible": { outline: "2px solid", outlineColor: "text.primary", outlineOffset: 2, zIndex: 1 },
    ...longPressable,
  } as const;

  const photo = (
    <ButtonBase onClick={() => onOpen(index)} tabIndex={-1} aria-label={`Show details for ${title}`}
      sx={{ display: "block", width: "100%", borderRadius: layout === "list" ? 0.5 : 0, overflow: "hidden" }}>
      <ListingImage src={candidate.payload.image_url} />
    </ButtonBase>
  );

  if (layout === "list" && compact) {
    return (
      <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)} {...handlers}
        sx={{ ...frame, display: "grid", gridTemplateColumns: "64px minmax(0, 1fr)", alignItems: "center", columnGap: 1.5,
          px: 1.5, py: 1.25, borderBottom: 1, borderColor: "divider" }}>
        {photo}
        <Box sx={{ minWidth: 0, display: "grid", gap: 0.5 }}>
          <Typography variant="body2" title={title} sx={{ fontWeight: 500, ...clamp }}>{titleText}</Typography>
          <Box sx={{ display: "flex", alignItems: "center", columnGap: 1.5, minWidth: 0 }}>
            <DecisionButton decision={candidate.decision} tabIndex={tab} />
            <Typography variant="caption" color="textSecondary" noWrap sx={figures}>
              <Box component="span" sx={{ color: "text.primary", fontWeight: 650 }}>{formatPrice(candidate.payload.price)}</Box>
              {` · ${sourceName(candidate.source)} · ${formatRelative(candidate.observed_at)}`}
            </Typography>
          </Box>
          {owner && <Owner candidate={candidate} />}
        </Box>
      </Box>
    );
  }

  if (layout === "list") {
    return (
      <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)} {...handlers}
        sx={{ ...frame, display: "grid", alignItems: "center", columnGap: 1.5, rowGap: 0.75, px: 1, py: 1,
          gridTemplateColumns: "64px minmax(0, 1fr) 120px 96px 88px", borderBottom: 1, borderColor: "divider" }}>
        {photo}
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 500 }} title={title}>{titleText}</Typography>
          {normalized && <Typography variant="caption" color="textSecondary" noWrap component="p" title={normalized}>{normalized}</Typography>}
          <Typography variant="caption" color="textSecondary" component="p" sx={figures}>
            {sourceName(candidate.source)} {candidate.external_id}
          </Typography>
          {owner && <Owner candidate={candidate} />}
        </Box>
        <Box><DecisionButton decision={candidate.decision} tabIndex={tab} /></Box>
        <Typography variant="body2" sx={{ fontWeight: 650, ...figures }}>{formatPrice(candidate.payload.price)}</Typography>
        {/* Aligned right, so every row ends in a straight edge. */}
        <Box sx={{ textAlign: "right" }}><Seen candidate={candidate} /></Box>
      </Box>
    );
  }

  return (
    <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)} {...handlers}
      sx={{ ...frame, display: "flex", flexDirection: "column", border: 1, borderColor: "divider", borderRadius: 1, overflow: "hidden" }}>
      {photo}
      <Box sx={{ p: 1.25, display: "flex", flexDirection: "column", gap: 0.75, flex: 1 }}>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", gap: 1 }}>
          <DecisionButton decision={candidate.decision} tabIndex={tab} />
          <Typography variant="caption" color="textSecondary" noWrap sx={figures}>{sourceName(candidate.source)}</Typography>
        </Stack>
        <Typography variant="body2" title={title} sx={{ fontWeight: 500, minHeight: "2.9em", ...clamp }}>
          {titleText}
        </Typography>
        {normalized && (
          <Typography variant="caption" color="textSecondary" noWrap title={`Compared title: ${normalized}`}>{normalized}</Typography>
        )}
        {owner && <Owner candidate={candidate} />}
        {/* Frames in a row share a height; pinning the price down lines it up across the row. */}
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "baseline", mt: "auto" }}>
          <Typography variant="body2" sx={{ fontWeight: 650, ...figures }}>{formatPrice(candidate.payload.price)}</Typography>
          <Seen candidate={candidate} />
        </Stack>
      </Box>
    </Box>
  );
});
