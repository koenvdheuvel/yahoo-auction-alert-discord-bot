import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Typography from "@mui/material/Typography";
import { useId, type ReactNode } from "react";

import { longPressable, useLongPress } from "../../lib/gestures";

/** A list of search cards: one column on phones, two on tablets. */
export function SearchCards({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box component="ul" aria-label={label} sx={{ listStyle: "none", m: 0, p: 0, display: "grid", gap: 1,
      gridTemplateColumns: { xs: "minmax(0, 1fr)", sm: "repeat(2, minmax(0, 1fr))" } }}>
      {children}
    </Box>
  );
}

interface Props {
  name: string;
  onOpen: () => void;
  /** Opens the search's other actions, like a long press on a Discord message. */
  onMenu: () => void;
  /** The lines under the name, such as the channel and the counts. */
  children: ReactNode;
  /** A button in the top right corner, such as Unregister. */
  end?: ReactNode;
}

/** One search as a card, for phones and tablets. A tap anywhere on the card opens the search. */
export function SearchCard({ name, onOpen, onMenu, children, end }: Props) {
  const press = useLongPress(onMenu);
  const id = useId();
  return (
    <Box component="li" sx={{ position: "relative", minWidth: 0 }}>
      {/* The name labels the button and the lines under it describe it, so screen readers hear the name first. */}
      <ButtonBase component="div" onClick={onOpen} {...press} aria-labelledby={`${id}-name`} aria-describedby={`${id}-detail`}
        sx={{ display: "block", width: "100%", height: "100%", textAlign: "left", p: 1.5, pr: end ? 7 : 1.5, borderRadius: 1,
          bgcolor: "background.paper", ...longPressable, "&:active": { bgcolor: "surface.hover" },
          "@media (hover: hover)": { "&:hover": { bgcolor: "surface.hover" } } }}>
        <Typography id={`${id}-name`} variant="subtitle1" component="span" sx={{ display: "block", overflowWrap: "anywhere" }}>
          {name}
        </Typography>
        <Box id={`${id}-detail`}>{children}</Box>
      </ButtonBase>
      {end && <Box sx={{ position: "absolute", top: 4, right: 4 }}>{end}</Box>}
    </Box>
  );
}
