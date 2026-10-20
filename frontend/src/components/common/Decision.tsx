import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Popover from "@mui/material/Popover";
import Typography from "@mui/material/Typography";
import { useId, useState } from "react";

import type { Decision, Reason, Verdict } from "../../api/types";
import { VERDICT_COLOR, VERDICTS } from "../../lib/vocabulary";
import { figures } from "../../theme";

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

/** The decision; selecting it shows why the bot decided so. */
export function DecisionButton({ decision, label, tabIndex }: { decision: Decision; label?: string; tabIndex?: number }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const id = useId();
  return (
    <>
      <ButtonBase
        onClick={(event) => setAnchor(event.currentTarget)}
        tabIndex={tabIndex}
        aria-haspopup="dialog"
        aria-expanded={anchor !== null}
        aria-controls={anchor ? id : undefined}
        aria-label={`${label ? `${label}: ` : ""}${VERDICTS[decision.verdict]}. Show why.`}
        sx={{ borderRadius: 1, px: 0.5, mx: -0.5, py: 0.25, "&:hover": { bgcolor: "action.hover" } }}
      >
        <VerdictText verdict={decision.verdict} />
      </ButtonBase>
      <Popover
        id={id}
        open={anchor !== null}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        slotProps={{ paper: { sx: { p: 2, maxWidth: 380, border: 1, borderColor: "divider" } } }}
      >
        {label && <Typography variant="caption" color="textSecondary" component="p">{label}</Typography>}
        <Typography variant="subtitle2" sx={{ mb: 1 }}>{WHY[decision.verdict]}</Typography>
        <ReasonList reasons={decision.reasons} />
        {decision.normalized_title && (
          <Typography variant="caption" color="textSecondary" component="p" sx={{ mt: 1.5 }}>
            Compared title: {decision.normalized_title}
          </Typography>
        )}
      </Popover>
    </>
  );
}
