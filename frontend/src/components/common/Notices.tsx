import Alert, { type AlertColor } from "@mui/material/Alert";
import Snackbar from "@mui/material/Snackbar";
import { useCallback, useState, type ReactNode } from "react";

import { NoticeContext, type Notify } from "./notify";

interface Notice {
  id: number;
  message: string;
  severity: AlertColor;
}

/** Short confirmations and failures at the top of the screen, one at a time. */
export function NoticeProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<Notice[]>([]);
  const notify = useCallback<Notify>((message, severity = "success") => {
    setQueue((current) => [...current.slice(-3), { id: Date.now() + Math.random(), message, severity }]);
  }, []);
  const current = queue[0];
  const close = useCallback(() => setQueue((items) => items.slice(1)), []);
  return (
    <NoticeContext.Provider value={notify}>
      {children}
      <Snackbar
        key={current?.id}
        open={current !== undefined}
        autoHideDuration={current?.severity === "error" ? 9000 : 4000}
        onClose={(_, reason) => reason !== "clickaway" && close()}
        // Top centre, as Discord shows its notices: clear of the account panel, the draft bar and bulk labels.
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        {current && (
          <Alert onClose={close} severity={current.severity} variant="filled" sx={{ maxWidth: 560 }}>
            {current.message}
          </Alert>
        )}
      </Snackbar>
    </NoticeContext.Provider>
  );
}
