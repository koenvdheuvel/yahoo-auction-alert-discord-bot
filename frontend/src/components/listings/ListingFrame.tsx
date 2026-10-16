import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Checkbox from "@mui/material/Checkbox";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { memo, type MouseEvent } from "react";

import type { Candidate, Label } from "../../api/types";
import { formatDateTime, formatPrice, formatRelative, safeUrl } from "../../lib/format";
import { listingTitle, surprisingNormalization } from "../../lib/listing";
import { LABELS, sourceName, VERDICTS } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { DecisionButton } from "../common/Decision";
import { ListingImage } from "../common/ListingImage";
import { LabelMark } from "../common/Marks";
import type { View } from "./FilterBar";
import { LabelButtons } from "./LabelButtons";

interface Props {
  candidate: Candidate;
  index: number;
  layout: View;
  /** The frame that keyboard focus returns to; only its controls are in the tab order. */
  active: boolean;
  selected: boolean;
  selecting: boolean;
  animateMark: boolean;
  onActivate: (index: number) => void;
  onSelect: (index: number, range: boolean) => void;
  onLabel: (candidate: Candidate, label: Label | null) => void;
  onOpen: (index: number) => void;
}

function Seen({ candidate }: { candidate: Candidate }) {
  const detail = `First seen with this decision ${formatDateTime(candidate.observed_at)}. Last seen ${formatDateTime(candidate.last_seen_at)}.`;
  return (
    <Tooltip title={detail}>
      <Typography variant="caption" color="text.secondary" sx={{ ...figures, whiteSpace: "nowrap" }}>
        {formatRelative(candidate.observed_at)}
      </Typography>
    </Tooltip>
  );
}

export const ListingFrame = memo(function ListingFrame(props: Props) {
  const { candidate, index, layout, active, selected, selecting, animateMark, onActivate, onSelect, onLabel, onOpen } = props;
  const title = listingTitle(candidate);
  const url = safeUrl(candidate.payload.url);
  const normalized = surprisingNormalization(candidate);
  const tab = active ? 0 : -1;
  const label = candidate.feedback;
  const summary = `${title}. ${VERDICTS[candidate.verdict]}. ${label ? `Labeled ${LABELS[label].name}` : "Not labeled"}.`;
  const select = (event: MouseEvent) => {
    event.stopPropagation();
    onSelect(index, event.shiftKey);
  };

  // Hidden until hover, focus or an active selection, so photos stay clean while browsing.
  // Touch screens cannot hover, so there it always shows.
  const reveal = { opacity: selecting || selected ? 1 : 0, "&:focus-within": { opacity: 1 }, "@media (hover: none)": { opacity: 1 } };
  const checkbox = (
    <Checkbox checked={selected} onClick={select} size="small" sx={{ p: 0.5 }}
      slotProps={{ input: { "aria-label": `Select ${title}`, tabIndex: tab } }} />
  );
  const titleText = url ? (
    <Link href={url} target="_blank" rel="noopener noreferrer" tabIndex={tab}>{title}</Link>
  ) : title;
  const labelButtons = (
    <LabelButtons value={label} onChange={(next) => onLabel(candidate, next)} subject={title} tabIndex={tab} />
  );

  const frame = {
    listStyle: "none",
    position: "relative",
    bgcolor: "background.paper",
    outline: "none",
    "&:hover .frame-select, &:focus-within .frame-select": { opacity: 1 },
    "&:focus-visible": { outline: "2px solid", outlineColor: "text.primary", outlineOffset: 2, zIndex: 1 },
  } as const;

  if (layout === "list") {
    return (
      <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)}
        sx={{ ...frame, display: "grid", alignItems: "center", columnGap: 1.5, rowGap: 0.75, px: 1, py: 1,
          gridTemplateColumns: { xs: "auto 56px minmax(0, 1fr)", md: "auto 64px minmax(0, 1fr) 120px 96px 88px auto" },
          borderBottom: 1, borderColor: "divider", bgcolor: selected ? "action.selected" : "background.paper" }}>
        <Box className="frame-select" sx={reveal}>{checkbox}</Box>
        <Box sx={{ position: "relative" }}>
          <ButtonBase onClick={() => onOpen(index)} tabIndex={-1} aria-label={`Show details for ${title}`}
            sx={{ display: "block", width: "100%", borderRadius: 0.5, overflow: "hidden" }}>
            <ListingImage src={candidate.payload.image_url} />
          </ButtonBase>
          {label && (
            <Box sx={{ position: "absolute", top: -6, right: -6, pointerEvents: "none" }}>
              <LabelMark label={label} size={26} animate={animateMark} />
            </Box>
          )}
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 500 }} title={title}>{titleText}</Typography>
          {normalized && <Typography variant="caption" color="text.secondary" noWrap component="p" title={normalized}>{normalized}</Typography>}
          <Typography variant="caption" color="text.secondary" component="p" sx={figures}>
            {sourceName(candidate.source)} {candidate.external_id}
          </Typography>
        </Box>
        <Box sx={{ gridColumn: { xs: "3", md: "auto" } }}><DecisionButton decision={candidate.decision} tabIndex={tab} /></Box>
        <Typography variant="body2" sx={{ fontWeight: 650, ...figures, display: { xs: "none", md: "block" } }}>
          {formatPrice(candidate.payload.price)}
        </Typography>
        <Box sx={{ display: { xs: "none", md: "block" } }}><Seen candidate={candidate} /></Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", gridColumn: { xs: "3", md: "auto" } }}>
          {labelButtons}
          {/* A phone row has no room for the name; the pressed button and the mark on the photo show it. */}
          <Typography variant="caption" sx={{ color: "secondary.main", fontWeight: 650, minWidth: 84, display: { xs: "none", sm: "block" } }}>
            {label ? LABELS[label].name : ""}
          </Typography>
        </Stack>
      </Box>
    );
  }

  return (
    <Box component="li" data-index={index} tabIndex={tab} aria-label={summary} onFocus={() => onActivate(index)}
      sx={{ ...frame, display: "flex", flexDirection: "column", border: 1, borderRadius: 1, overflow: "hidden",
        borderColor: selected ? "text.primary" : "divider",
        boxShadow: selected ? "inset 0 0 0 1px var(--mui-palette-text-primary)" : "none" }}>
      <Box sx={{ position: "relative" }}>
        <ButtonBase onClick={() => onOpen(index)} tabIndex={-1} aria-label={`Show details for ${title}`}
          sx={{ display: "block", width: "100%" }}>
          <ListingImage src={candidate.payload.image_url} />
        </ButtonBase>
        <Box className="frame-select" sx={{ ...reveal, position: "absolute", top: 4, left: 4, bgcolor: "background.paper",
          borderRadius: 1 }}>{checkbox}</Box>
        {label && (
          <>
            <Box sx={{ position: "absolute", top: 2, right: 2, pointerEvents: "none" }}>
              <LabelMark label={label} animate={animateMark} />
            </Box>
            <Box sx={{ position: "absolute", left: 6, bottom: 6, px: 0.75, py: 0.25, borderRadius: 0.75,
              bgcolor: "background.paper", color: "secondary.main", fontSize: "0.75rem", fontWeight: 650 }}>
              {LABELS[label].name}
            </Box>
          </>
        )}
      </Box>
      <Box sx={{ p: 1.25, display: "flex", flexDirection: "column", gap: 0.75, flex: 1 }}>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", gap: 1 }}>
          <DecisionButton decision={candidate.decision} tabIndex={tab} />
          <Typography variant="caption" color="text.secondary" noWrap sx={figures}>{sourceName(candidate.source)}</Typography>
        </Stack>
        <Typography variant="body2" title={title} sx={{ fontWeight: 500, minHeight: "2.9em", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", overflowWrap: "anywhere" }}>
          {titleText}
        </Typography>
        {normalized && (
          <Typography variant="caption" color="text.secondary" noWrap title={`Compared title: ${normalized}`}>{normalized}</Typography>
        )}
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <Typography variant="body2" sx={{ fontWeight: 650, ...figures }}>{formatPrice(candidate.payload.price)}</Typography>
          <Seen candidate={candidate} />
        </Stack>
        {/* Frames in a row share a height; pinning the labels down lines them up across the row. */}
        <Box sx={{ mt: "auto", pt: 0.25 }}>{labelButtons}</Box>
      </Box>
    </Box>
  );
});
