import HelpOutlineOutlined from "@mui/icons-material/HelpOutlineOutlined";
import Button from "@mui/material/Button";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { usePhone } from "../../lib/responsive";
import { SheetDialog } from "./Sheet";

/**
 * A small "?" that explains what is next to it. Opens on hover, on keyboard focus and on tap; on
 * phones the explanation opens as a sheet, since a long tooltip is hard to read there.
 */
export function HelpTip({ title, text }: { title: string; text: string }) {
  const phone = usePhone();
  const [open, setOpen] = useState(false);
  const button = (
    <IconButton size="small" aria-label={`About ${title}`} onClick={phone ? () => setOpen(true) : undefined}
      // Touch screens make the button finger-sized; the negative margin keeps the line it sits in as tall as before.
      sx={{ p: 0.25, ml: 0.5, color: "text.secondary", verticalAlign: "middle", "@media (pointer: coarse)": { my: -1.5 } }}>
      <HelpOutlineOutlined sx={{ fontSize: 16 }} />
    </IconButton>
  );
  if (phone) {
    return (
      <>
        {button}
        <SheetDialog open={open} onClose={() => setOpen(false)} maxWidth="xs" aria-label={`About ${title}`}>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent><Typography variant="body2">{text}</Typography></DialogContent>
          <DialogActions><Button onClick={() => setOpen(false)} color="inherit">Close</Button></DialogActions>
        </SheetDialog>
      </>
    );
  }
  // The theme keeps tooltips from opening on touch; this one is meant to open on a tap.
  return (
    <Tooltip title={text} describeChild enterTouchDelay={0} leaveTouchDelay={8000} disableTouchListener={false}>
      {button}
    </Tooltip>
  );
}
