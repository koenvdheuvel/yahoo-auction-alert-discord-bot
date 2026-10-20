import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { memo } from "react";

import type { Candidate } from "../../api/types";
import { formatDateTime, formatPrice, formatRelative, safeUrl } from "../../lib/format";
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
  onActivate: (index: number) => void;
  onOpen: (index: number) => void;
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

export const ListingFrame = memo(function ListingFrame(props: Props) {
  const { candidate, index, layout, active, onActivate, onOpen } = props;
  const title = listingTitle(candidate);
  const url = safeUrl(candidate.payload.url);
  const normalized = surprisingNormalization(candidate);
  const tab = active ? 0 : -1;
  const summary = `${title}. ${VERDICTS[candidate.verdict]}.`;

  const titleText = url ? (
    <Link href={url} target="_blank" rel="noopener noreferrer" tabIndex={tab}>{title}</Link>
  ) : title;

  const frame = {
    listStyle: "none",
    position: "relative",
    bgcolor: "background.paper",
    outline: "none",
    "&:focus-visible": { outline: "2px solid", outlineColor: "text.primary", outlineOffset: 2, zIndex: 1 },
  } as const;

  if (layout === "list") {
    return (
      <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)}
        sx={{ ...frame, display: "grid", alignItems: "center", columnGap: 1.5, rowGap: 0.75, px: 1, py: 1,
          gridTemplateColumns: { xs: "56px minmax(0, 1fr)", md: "64px minmax(0, 1fr) 120px 96px 88px" },
          borderBottom: 1, borderColor: "divider" }}>
        <ButtonBase onClick={() => onOpen(index)} tabIndex={-1} aria-label={`Show details for ${title}`}
          sx={{ display: "block", width: "100%", borderRadius: 0.5, overflow: "hidden" }}>
          <ListingImage src={candidate.payload.image_url} />
        </ButtonBase>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 500 }} title={title}>{titleText}</Typography>
          {normalized && <Typography variant="caption" color="textSecondary" noWrap component="p" title={normalized}>{normalized}</Typography>}
          <Typography variant="caption" color="textSecondary" component="p" sx={figures}>
            {sourceName(candidate.source)} {candidate.external_id}
          </Typography>
        </Box>
        <Box sx={{ gridColumn: { xs: "2", md: "auto" } }}><DecisionButton decision={candidate.decision} tabIndex={tab} /></Box>
        <Typography variant="body2" sx={{ fontWeight: 650, ...figures, display: { xs: "none", md: "block" } }}>
          {formatPrice(candidate.payload.price)}
        </Typography>
        {/* Aligned right, so every row ends in a straight edge. */}
        <Box sx={{ display: { xs: "none", md: "block" }, textAlign: "right" }}><Seen candidate={candidate} /></Box>
      </Box>
    );
  }

  return (
    <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)}
      sx={{ ...frame, display: "flex", flexDirection: "column", border: 1, borderColor: "divider", borderRadius: 1, overflow: "hidden" }}>
      <ButtonBase onClick={() => onOpen(index)} tabIndex={-1} aria-label={`Show details for ${title}`}
        sx={{ display: "block", width: "100%" }}>
        <ListingImage src={candidate.payload.image_url} />
      </ButtonBase>
      <Box sx={{ p: 1.25, display: "flex", flexDirection: "column", gap: 0.75, flex: 1 }}>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", gap: 1 }}>
          <DecisionButton decision={candidate.decision} tabIndex={tab} />
          <Typography variant="caption" color="textSecondary" noWrap sx={figures}>{sourceName(candidate.source)}</Typography>
        </Stack>
        <Typography variant="body2" title={title} sx={{ fontWeight: 500, minHeight: "2.9em", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", overflowWrap: "anywhere" }}>
          {titleText}
        </Typography>
        {normalized && (
          <Typography variant="caption" color="textSecondary" noWrap title={`Compared title: ${normalized}`}>{normalized}</Typography>
        )}
        {/* Frames in a row share a height; pinning the price down lines it up across the row. */}
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "baseline", mt: "auto" }}>
          <Typography variant="body2" sx={{ fontWeight: 650, ...figures }}>{formatPrice(candidate.payload.price)}</Typography>
          <Seen candidate={candidate} />
        </Stack>
      </Box>
    </Box>
  );
});
