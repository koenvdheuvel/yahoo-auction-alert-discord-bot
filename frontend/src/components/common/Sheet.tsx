import Box from "@mui/material/Box";
import Dialog, { type DialogProps } from "@mui/material/Dialog";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Slide, { type SlideProps } from "@mui/material/Slide";
import type { TransitionProps } from "@mui/material/transitions";
import Typography from "@mui/material/Typography";
import { useId, useRef, type ReactNode } from "react";

import { useSwipe } from "../../lib/gestures";
import { useKeyboardArea, usePhone } from "../../lib/responsive";

// Content scrolled away from its top scrolls back up; only a drag that starts at the top moves the sheet.
// A drag in a text field selects text or moves the cursor, and closing would lose what was typed.
function keepsSheet(target: Element): boolean {
  if (target.closest("input, textarea, select, [contenteditable='true']")) return true;
  const content = target.closest(".MuiDialogContent-root");
  return content !== null && content.scrollTop > 0;
}

function SlideUp(props: TransitionProps & { children: SlideProps["children"] }) {
  return <Slide direction="up" {...props} />;
}

const sheetPaper = {
  m: 0,
  width: "100%",
  maxWidth: "100%",
  maxHeight: "calc(100% - 24px - env(safe-area-inset-top, 0px))",
  borderRadius: "16px 16px 0 0",
  pb: "env(safe-area-inset-bottom, 0px)",
  overscrollBehavior: "contain",
  // The main action on top and Cancel under it, each across the whole sheet, like an app's sheet.
  "& .MuiDialogActions-root": {
    flexDirection: "column-reverse", alignItems: "stretch", gap: 1, px: 2, pt: 1, pb: 2,
    "& > :not(style) ~ :not(style)": { ml: 0 },
  },
} as const;

/**
 * A dialog that opens as a sheet from the bottom of the screen on phones. A drag down closes it,
 * unless closing is not allowed at the moment (no `onClose`). Larger screens get the plain dialog.
 */
export function SheetDialog(props: DialogProps) {
  const { children, onClose, sx, slotProps, ...rest } = props;
  const phone = usePhone();
  const keyboard = useKeyboardArea();
  const handle = useRef<HTMLDivElement>(null);
  const swipe = useSwipe({
    directions: ["down"],
    ignore: keepsSheet,
    onDrag: (offset) => {
      const element = handle.current?.closest<HTMLElement>(".MuiDialog-paper");
      if (!element) return;
      element.style.transition = offset ? "none" : "transform 200ms ease-out";
      element.style.transform = offset ? `translateY(${offset}px)` : "";
    },
    onSwipe: () => onClose?.({}, "backdropClick"),
  });

  if (!phone) return <Dialog {...props} />;
  const paperSlot = typeof slotProps?.paper === "object" ? slotProps.paper : {};
  return (
    <Dialog
      {...rest}
      onClose={onClose}
      sx={sx}
      fullWidth
      scroll="paper"
      slots={{ transition: SlideUp }}
      slotProps={{
        ...slotProps,
        // While the on-screen keyboard is up, the sheet fits the part of the screen above it.
        root: { style: keyboard.bottom ? { top: keyboard.top, bottom: keyboard.bottom } : undefined },
        container: { sx: { alignItems: "flex-end" } },
        paper: { ...paperSlot, sx: sheetPaper, ...(onClose ? swipe : {}) },
      }}
    >
      {/* The handle shows the sheet can be dragged down. */}
      <Box ref={handle} aria-hidden="true" sx={{ flex: "none", width: 36, height: 4, borderRadius: 2, bgcolor: "text.disabled",
        opacity: 0.6, mx: "auto", mt: 1 }} />
      {children}
    </Dialog>
  );
}

export interface SheetAction {
  label: string;
  icon?: ReactNode;
  /** Opens this address in a new tab. */
  href?: string;
  onSelect?: () => void;
  disabled?: boolean;
}

interface ActionSheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Shown under the title, such as a photo and the decision. */
  children?: ReactNode;
  actions: SheetAction[];
}

/** The actions for one thing, as a sheet. A long press opens it, like a long press on a Discord message. */
export function ActionSheet({ open, onClose, title, children, actions }: ActionSheetProps) {
  const id = useId();
  return (
    <SheetDialog open={open} onClose={onClose} maxWidth="xs" aria-labelledby={id}>
      <Box sx={{ px: 2.5, pt: 1.5, pb: 1 }}>
        <Typography id={id} variant="subtitle1" component="h2" sx={{ overflowWrap: "anywhere" }}>{title}</Typography>
        {children}
      </Box>
      <List sx={{ pt: 0, pb: 1 }}>
        {actions.map((action) => {
          const content = (
            <>
              {action.icon && <ListItemIcon>{action.icon}</ListItemIcon>}
              <ListItemText primary={action.label} />
            </>
          );
          return action.href ? (
            <ListItemButton key={action.label} component="a" href={action.href} target="_blank" rel="noopener noreferrer"
              disabled={action.disabled} onClick={onClose}>
              {content}
            </ListItemButton>
          ) : (
            <ListItemButton key={action.label} disabled={action.disabled} onClick={() => { onClose(); action.onSelect?.(); }}>
              {content}
            </ListItemButton>
          );
        })}
      </List>
    </SheetDialog>
  );
}
