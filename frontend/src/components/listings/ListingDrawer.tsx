import ChevronLeft from "@mui/icons-material/ChevronLeft";
import ChevronRight from "@mui/icons-material/ChevronRight";
import Close from "@mui/icons-material/Close";
import OpenInNew from "@mui/icons-material/OpenInNew";
import ScienceOutlined from "@mui/icons-material/ScienceOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { KeyboardEvent, ReactNode } from "react";

import type { Candidate, Label } from "../../api/types";
import { formatDateTime, formatPrice, safeUrl } from "../../lib/format";
import { isTyping } from "../../lib/hooks";
import { listingTitle } from "../../lib/listing";
import { LABEL_ORDER, LABELS, sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { ReasonList, VerdictText } from "../common/Decision";
import { ListingImage } from "../common/ListingImage";
import { LabelMark } from "../common/Marks";
import { LabelButtons } from "./LabelButtons";

interface Props {
  candidate: Candidate | null;
  position: string;
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onClose: () => void;
  onLabel: (candidate: Candidate, label: Label | null) => void;
  onTestTitle: (candidate: Candidate) => void;
}

function Fact({ name, children }: { name: string; children: ReactNode }) {
  return (
    <>
      <Typography component="dt" variant="body2" color="text.secondary">{name}</Typography>
      <Typography component="dd" variant="body2" sx={{ m: 0, overflowWrap: "anywhere", ...figures }}>{children}</Typography>
    </>
  );
}

const ORIGINS: Record<Candidate["origin"], string> = {
  live: "Saved by a check",
  delivery_import: "Imported from posted messages",
  item_import: "Imported from tracked listings",
};

/** One listing in full, with the same label keys as the grid. */
export function ListingDrawer(props: Props) {
  const { candidate, position, hasPrevious, hasNext, onPrevious, onNext, onClose, onLabel, onTestTitle } = props;

  const onKeyDown = (event: KeyboardEvent) => {
    if (!candidate || isTyping(event) || event.metaKey || event.ctrlKey || event.altKey) return;
    const label = LABEL_ORDER.find((name) => LABELS[name].key === event.key);
    if (label) onLabel(candidate, candidate.feedback === label ? null : label);
    else if (event.key === "0") onLabel(candidate, null);
    else if ((event.key === "j" || event.key === "ArrowRight") && hasNext) onNext();
    else if ((event.key === "k" || event.key === "ArrowLeft") && hasPrevious) onPrevious();
    else return;
    event.preventDefault();
  };

  const url = candidate ? safeUrl(candidate.payload.url) : null;
  const title = candidate ? listingTitle(candidate) : "";
  return (
    <Drawer anchor="right" open={candidate !== null} onClose={onClose} sx={{ zIndex: (theme) => theme.zIndex.modal }}
      slotProps={{ paper: { sx: { width: { xs: "100%", sm: 460 } }, onKeyDown, "aria-label": "Listing details" } }}>
      {candidate && (
        <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
          <Stack direction="row" sx={{ alignItems: "center", px: 1.5, py: 1, borderBottom: 1, borderColor: "divider", gap: 0.5 }}>
            <Tooltip title="Previous (k)"><span>
              <IconButton onClick={onPrevious} disabled={!hasPrevious} aria-label="Previous listing"><ChevronLeft /></IconButton>
            </span></Tooltip>
            <Tooltip title="Next (j)"><span>
              <IconButton onClick={onNext} disabled={!hasNext} aria-label="Next listing"><ChevronRight /></IconButton>
            </span></Tooltip>
            <Typography variant="caption" color="text.secondary" sx={{ flex: 1, ...figures }}>{position}</Typography>
            <IconButton onClick={onClose} aria-label="Close details"><Close /></IconButton>
          </Stack>
          <Box sx={{ position: "relative" }}>
            <ListingImage src={candidate.payload.image_url} ratio="4 / 3" />
            {candidate.feedback && (
              <Box sx={{ position: "absolute", top: 8, right: 8 }}><LabelMark label={candidate.feedback} size={64} /></Box>
            )}
          </Box>
          <Box sx={{ p: 2.5, display: "grid", gap: 2 }}>
            <Box>
              <Typography variant="h2" component="h2" sx={{ fontStretch: "100%", overflowWrap: "anywhere" }}>{title}</Typography>
              {candidate.normalized_title && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, overflowWrap: "anywhere" }}>
                  Compared title: {candidate.normalized_title}
                </Typography>
              )}
            </Box>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
              <LabelButtons value={candidate.feedback} onChange={(label) => onLabel(candidate, label)} subject={title} />
              <Typography variant="body2" sx={{ color: candidate.feedback ? "secondary.main" : "text.secondary", fontWeight: 650 }}>
                {candidate.feedback ? LABELS[candidate.feedback].name : "Not labeled"}
              </Typography>
            </Stack>
            <Box>
              <VerdictText verdict={candidate.verdict} />
              <Box sx={{ mt: 1 }}><ReasonList reasons={candidate.decision.reasons} /></Box>
            </Box>
            <Divider />
            <Box component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: "max-content 1fr", columnGap: 2, rowGap: 0.75 }}>
              <Fact name="Price">{formatPrice(candidate.payload.price)}</Fact>
              <Fact name="Marketplace">{sourceName(candidate.source)}</Fact>
              <Fact name="Listing ID">{candidate.external_id || "Not saved"}</Fact>
              {typeof candidate.payload.stock === "number" && <Fact name="Stock">{candidate.payload.stock}</Fact>}
              {candidate.payload.end_time && <Fact name="Ends">{formatDateTime(candidate.payload.end_time)}</Fact>}
              <Fact name="Search">{candidate.search_query}</Fact>
              <Fact name="First seen">{formatDateTime(candidate.observed_at)}</Fact>
              <Fact name="Last seen">{formatDateTime(candidate.last_seen_at)}</Fact>
              <Fact name="Saved by">{ORIGINS[candidate.origin]}</Fact>
            </Box>
            {candidate.incomplete && (
              <Typography variant="body2" color="warning.main">
                Some listing facts were missing or cut short, so replay keeps this listing in review.
              </Typography>
            )}
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
              {url && (
                <Button component={Link} href={url} target="_blank" rel="noopener noreferrer" variant="outlined"
                  color="inherit" endIcon={<OpenInNew />} underline="none">
                  Open on {sourceName(candidate.source)}
                </Button>
              )}
              <Button variant="outlined" color="inherit" startIcon={<ScienceOutlined />} onClick={() => onTestTitle(candidate)}>
                Test with the draft
              </Button>
            </Stack>
          </Box>
        </Box>
      )}
    </Drawer>
  );
}
