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
import useMediaQuery from "@mui/material/useMediaQuery";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { useSession } from "../../api/hooks";
import type { Candidate } from "../../api/types";
import { channelLabel } from "../../lib/channels";
import { formatDateTime, formatPrice, safeUrl } from "../../lib/format";
import { useSwipe, type Direction } from "../../lib/gestures";
import { isTyping } from "../../lib/hooks";
import { listingTitle } from "../../lib/listing";
import { usePhone } from "../../lib/responsive";
import { sourceName } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { ReasonList, VerdictText } from "../common/Decision";
import { FollowButton } from "../common/FollowButton";
import { ListingImage } from "../common/ListingImage";

interface Props {
  candidate: Candidate | null;
  position: string;
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onClose: () => void;
  onTestTitle: (candidate: Candidate) => void;
  /** Opens the registered search the listing belongs to. */
  onOpenSearch?: (alertId: string) => void;
  /** Opens the channel the listing was saved in. */
  onOpenChannel?: (channelId: string) => void;
}

type Shown = Pick<Props, "candidate" | "position" | "hasPrevious" | "hasNext">;

function Fact({ name, children }: { name: string; children: ReactNode }) {
  return (
    <>
      <Typography component="dt" variant="body2" color="textSecondary">{name}</Typography>
      <Typography component="dd" variant="body2" sx={{ m: 0, overflowWrap: "anywhere", ...figures }}>{children}</Typography>
    </>
  );
}

const ORIGINS: Record<Candidate["origin"], string> = {
  live: "Saved by a check",
  delivery_import: "Imported from posted messages",
  item_import: "Imported from tracked listings",
};

// How long a listing takes to slide out, and the next one to slide in, after a swipe.
const SLIDE_MS = 160;

/**
 * One listing in full. j and k move through the list, like in the grid. On phones it is a sheet over
 * the whole screen: a swipe sideways moves to the next or previous listing, a drag down closes it.
 */
export function ListingDrawer(props: Props) {
  const { onPrevious, onNext, onClose, onTestTitle, onOpenSearch, onOpenChannel } = props;
  const phone = usePhone();
  const still = useMediaQuery("(prefers-reduced-motion: reduce)");
  const root = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  // The side the listing that comes next slides in from, until it has.
  const incoming = useRef<Direction | null>(null);
  // Set while a listing slides out; swipes and keys wait for it.
  const timer = useRef<number | undefined>(undefined);
  const [turns, setTurns] = useState(0);
  // While the drawer slides away it keeps showing the listing it had.
  const current: Shown = { candidate: props.candidate, position: props.position, hasPrevious: props.hasPrevious, hasNext: props.hasNext };
  const [last, setLast] = useState(current);
  if (current.candidate && (Object.keys(current) as (keyof Shown)[]).some((key) => current[key] !== last[key])) setLast(current);
  const { candidate, position, hasPrevious, hasNext } = current.candidate ? current : last;

  useEffect(() => () => window.clearTimeout(timer.current), []);

  // After a swipe the new listing starts at its top and slides in from the side the finger came from.
  useLayoutEffect(() => {
    if (!turns) return;
    if (scroller.current) scroller.current.scrollTop = 0;
    const element = page.current;
    const from = incoming.current;
    incoming.current = null;
    if (!element) return;
    // With reduced motion there is no slide: the new listing shows in place, without the drag's offset.
    element.style.transition = "none";
    element.style.transform = from ? `translateX(${from === "left" ? "100%" : "-100%"})` : "";
    if (!from) return;
    // Reading the size applies the start position before the slide begins.
    element.getBoundingClientRect();
    element.style.transition = `transform ${SLIDE_MS}ms ease-out`;
    element.style.transform = "";
  }, [turns]);

  const turn = (direction: Direction) => {
    if (timer.current !== undefined) return;
    const go = direction === "left" ? onNext : onPrevious;
    const element = page.current;
    if (!element || still) {
      go();
      setTurns((count) => count + 1);
      return;
    }
    element.style.transition = `transform ${SLIDE_MS}ms ease-in`;
    element.style.transform = `translateX(${direction === "left" ? "-100%" : "100%"})`;
    timer.current = window.setTimeout(() => {
      timer.current = undefined;
      incoming.current = direction;
      go();
      setTurns((count) => count + 1);
    }, SLIDE_MS);
  };
  const previous = phone ? () => turn("right") : onPrevious;
  const next = phone ? () => turn("left") : onNext;

  const directions: Direction[] = [];
  if (hasNext) directions.push("left");
  if (hasPrevious) directions.push("right");
  const paging = useSwipe({
    directions,
    onDrag: (offset) => {
      const element = page.current;
      if (!element || timer.current !== undefined) return;
      element.style.transition = offset ? "none" : `transform ${SLIDE_MS}ms ease-out`;
      element.style.transform = offset ? `translateX(${offset}px)` : "";
    },
    onSwipe: turn,
  });
  const closing = useSwipe({
    directions: ["down"],
    // Content scrolled away from its top scrolls back up; only a drag that starts at the top moves the sheet.
    ignore: (target) => Boolean(scroller.current?.contains(target) && scroller.current.scrollTop > 0),
    onDrag: (offset) => {
      const paper = root.current?.closest<HTMLElement>(".MuiDrawer-paper");
      if (!paper) return;
      paper.style.transition = offset ? "none" : "transform 200ms ease-out";
      paper.style.transform = offset ? `translateY(${offset}px)` : "";
    },
    onSwipe: () => onClose(),
  });

  const onKeyDown = (event: KeyboardEvent) => {
    if (!candidate || isTyping(event) || event.metaKey || event.ctrlKey || event.altKey) return;
    if ((event.key === "j" || event.key === "ArrowRight") && hasNext) next();
    else if ((event.key === "k" || event.key === "ArrowLeft") && hasPrevious) previous();
    else return;
    event.preventDefault();
  };

  const url = candidate ? safeUrl(candidate.payload.url) : null;
  const title = candidate ? listingTitle(candidate) : "";
  // 🔔 follows a stored listing; listings the bot filtered were never stored.
  const notifications = useSession().data?.features?.notifications ?? false;
  return (
    <Drawer anchor={phone ? "bottom" : "right"} open={props.candidate !== null} onClose={onClose}
      sx={{ zIndex: (theme) => theme.zIndex.modal }}
      slotProps={{ paper: { sx: phone
        // The whole screen, below the notch or the status bar.
        ? { height: "100%", pt: "env(safe-area-inset-top, 0px)", overflow: "hidden" }
        : { width: 460, overflow: "hidden" }, onKeyDown, "aria-label": "Listing details" } }}>
      {candidate && (
        // The sheet keeps its own sideways swipes; they do not open the server and channel lists.
        <Box ref={root} data-no-swipe {...(phone ? closing : {})}
          sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <Stack direction="row" sx={{ flex: "none", alignItems: "center", px: 1.5, py: 1, borderBottom: 1, borderColor: "divider", gap: 0.5 }}>
            <Tooltip title="Previous (k)"><span>
              <IconButton onClick={previous} disabled={!hasPrevious} aria-label="Previous listing"><ChevronLeft /></IconButton>
            </span></Tooltip>
            <Tooltip title="Next (j)"><span>
              <IconButton onClick={next} disabled={!hasNext} aria-label="Next listing"><ChevronRight /></IconButton>
            </span></Tooltip>
            <Typography variant="caption" color="textSecondary" sx={{ flex: 1, ...figures }}>{position}</Typography>
            <IconButton onClick={onClose} aria-label="Close details"><Close /></IconButton>
          </Stack>
          <Box ref={scroller} {...(phone ? paging : {})}
            sx={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden",
              // A drag at the top moves the sheet, not the page under it; sideways moves are the swipes.
              ...(phone && { overscrollBehavior: "none", touchAction: "pan-y pinch-zoom" }) }}>
            <Box ref={page}>
              <ListingImage src={candidate.payload.image_url} ratio="4 / 3" />
              <Box sx={{ p: 2.5, display: "grid", gap: 2, pb: phone ? "calc(20px + env(safe-area-inset-bottom, 0px))" : 2.5 }}>
                <Box>
                  <Typography variant="h2" component="h2" sx={{ fontStretch: "100%", overflowWrap: "anywhere" }}>{title}</Typography>
                  {candidate.normalized_title && (
                    <Typography variant="body2" color="textSecondary" sx={{ mt: 0.75, overflowWrap: "anywhere" }}>
                      Compared title: {candidate.normalized_title}
                    </Typography>
                  )}
                </Box>
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
                  <Fact name="Search">
                    {candidate.alert_id !== null && onOpenSearch ? (
                      <Link component="button" type="button" variant="body2" onClick={() => onOpenSearch(candidate.alert_id!)}
                        sx={{ textAlign: "left", overflowWrap: "anywhere" }}>{candidate.search_query}</Link>
                    ) : candidate.search_query}
                    {candidate.alert_id === null && (
                      <Typography variant="caption" color="textSecondary" component="p">
                        This search is no longer registered. Its saved listings are kept.
                      </Typography>
                    )}
                  </Fact>
                  <Fact name="Channel">
                    {onOpenChannel ? (
                      <Link component="button" type="button" variant="body2" onClick={() => onOpenChannel(candidate.channel_id)}
                        sx={{ textAlign: "left" }}>{channelLabel(candidate.channel_id, candidate.channel_name)}</Link>
                    ) : channelLabel(candidate.channel_id, candidate.channel_name)}
                  </Fact>
                  <Fact name="First seen">{formatDateTime(candidate.observed_at)}</Fact>
                  <Fact name="Last seen">{formatDateTime(candidate.last_seen_at)}</Fact>
                  <Fact name="Saved by">{ORIGINS[candidate.origin]}</Fact>
                </Box>
                {candidate.incomplete && (
                  <Typography variant="body2" color="warning">
                    Some listing facts were missing or cut short, so replay keeps this listing in review.
                  </Typography>
                )}
                {/* Phones stack the buttons across the sheet, within reach of a thumb. */}
                <Stack direction={phone ? "column" : "row"} spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
                  {url && (
                    <Button component={Link} href={url} target="_blank" rel="noopener noreferrer" variant="outlined"
                      color="inherit" endIcon={<OpenInNew />} underline="none">
                      Open on {sourceName(candidate.source)}
                    </Button>
                  )}
                  <Button variant="outlined" color="inherit" startIcon={<ScienceOutlined />} onClick={() => onTestTitle(candidate)}>
                    Test with the draft
                  </Button>
                  {notifications && candidate.item_id && (
                    <FollowButton itemId={candidate.item_id} following={candidate.subscribed ?? false} />
                  )}
                </Stack>
              </Box>
            </Box>
          </Box>
        </Box>
      )}
    </Drawer>
  );
}
