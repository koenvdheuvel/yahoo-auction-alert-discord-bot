import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Popover from "@mui/material/Popover";
import Typography from "@mui/material/Typography";
import { useId, useState } from "react";

import type { Decision, Reason, Verdict } from "../../api/types";
import { usePhone } from "../../lib/responsive";
import { VERDICT_COLOR, VERDICTS } from "../../lib/vocabulary";
import { figures } from "../../theme";
import { SheetDialog } from "./Sheet";

/** The bot's decision, printed: a square of its ink and the decision's name. */
export function VerdictText({ verdict }: { verdict: Verdict }) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 0.75, color: VERDICT_COLOR[verdict],
      fontWeight: 650, fontSize: "0.8125rem", ...figures }}>
      <Box component="span" aria-hidden="true" sx={{ width: 8, height: 8, bgcolor: "currentColor", flex: "none" }} />
      {VERDICTS[verdict]}
    </Box>
  );
}

const WHY: Record<Verdict, string> = {
  accepted: "Why it is allowed",
  filtered: "Why it is filtered",
  review: "Why it needs review",
};

export function ReasonList({ reasons, dense = false }: { reasons: Reason[]; dense?: boolean }) {
  if (!reasons.length) {
    return <Typography variant="body2" color="textSecondary">No reasons were saved for this decision.</Typography>;
  }
  return (
    <Box component="ul" sx={{ m: 0, pl: 2.25, display: "grid", gap: dense ? 0.25 : 0.5 }}>
      {reasons.map((reason, index) => (
        <Typography component="li" variant="body2" key={`${reason.code}-${index}`}>{reason.message || reason.code}</Typography>
      ))}
    </Box>
  );
}

function ComparedTitle({ decision }: { decision: Decision }) {
  if (!decision.normalized_title) return null;
  return (
    <Typography variant="caption" color="textSecondary" component="p" sx={{ mt: 1.5, overflowWrap: "anywhere" }}>
      Compared title: {decision.normalized_title}
    </Typography>
  );
}

/** The decision; selecting it shows why the bot decided so. Phones show the reasons in a sheet. */
export function DecisionButton({ decision, label, tabIndex }: { decision: Decision; label?: string; tabIndex?: number }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const phone = usePhone();
  const id = useId();
  const close = () => setAnchor(null);
  return (
    <>
      <ButtonBase
        onClick={(event) => setAnchor(event.currentTarget)}
        tabIndex={tabIndex}
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        aria-controls={anchor ? id : undefined}
        aria-label={`${label ? `${label}: ` : ""}${VERDICTS[decision.verdict]}. Show why.`}
        sx={{
          borderRadius: 1, px: 0.5, mx: -0.5, py: 0.25,
          "@media (hover: hover)": { "&:hover": { bgcolor: "action.hover" } },
          // A finger gets 44 pixels of height; the negative margin keeps the line as it was.
          "@media (pointer: coarse)": { py: "14.5px", my: "-12.5px" },
        }}
      >
        <VerdictText verdict={decision.verdict} />
      </ButtonBase>
      {phone ? (
        <SheetDialog id={id} open={anchor !== null} onClose={close} maxWidth="xs" aria-labelledby={`${id}-title`}>
          <DialogTitle id={`${id}-title`} sx={{ pb: 1 }}>
            {label && <Typography variant="caption" color="textSecondary" component="span" sx={{ display: "block" }}>{label}</Typography>}
            {WHY[decision.verdict]}
          </DialogTitle>
          <DialogContent>
            <ReasonList reasons={decision.reasons} />
            <ComparedTitle decision={decision} />
          </DialogContent>
          <DialogActions><Button onClick={close} color="inherit">Close</Button></DialogActions>
        </SheetDialog>
      ) : (
        <Popover
          id={id}
          open={anchor !== null}
          anchorEl={anchor}
          onClose={close}
          anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
          slotProps={{ paper: { sx: { p: 2, maxWidth: 380, border: 1, borderColor: "divider" } } }}
        >
          {label && <Typography variant="caption" color="textSecondary" component="p">{label}</Typography>}
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{WHY[decision.verdict]}</Typography>
          <ReasonList reasons={decision.reasons} />
          <ComparedTitle decision={decision} />
        </Popover>
      )}
    </>
  );
}
