import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { ApiError } from "../../api/client";
import { errorMessage } from "../../lib/errors";

/** A failed load, with what happened and a way to try again. */
export function LoadError({ error, onRetry, what }: { error: unknown; onRetry?: () => void; what: string }) {
  const offline = error instanceof ApiError && error.status === 0;
  return (
    <Alert severity="error" sx={{ alignItems: "center" }}
      action={onRetry && <Button color="inherit" size="small" onClick={onRetry}>Try again</Button>}>
      {offline ? errorMessage(error) : `${what} could not be loaded: ${errorMessage(error)}`}
    </Alert>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <Box sx={{ py: 6, px: 3, textAlign: "left", maxWidth: 560 }}>
      <Typography variant="h3" component="p">{title}</Typography>
      {children && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{children}</Typography>}
      {action && <Box sx={{ mt: 2 }}>{action}</Box>}
    </Box>
  );
}

interface ConfirmProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirm: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({ open, title, children, confirm, busy = false, onConfirm, onClose }: ConfirmProps) {
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" aria-labelledby="confirm-title">
      <DialogTitle id="confirm-title">{title}</DialogTitle>
      <DialogContent>{children}</DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy} color="inherit">Cancel</Button>
        <Button onClick={onConfirm} disabled={busy} variant="contained" autoFocus>{busy ? "Working" : confirm}</Button>
      </DialogActions>
    </Dialog>
  );
}
