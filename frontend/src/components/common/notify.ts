import type { AlertColor } from "@mui/material/Alert";
import { createContext, useContext } from "react";

export type Notify = (message: string, severity?: AlertColor) => void;

export const NoticeContext = createContext<Notify>(() => undefined);

/** Shows a short confirmation or failure at the bottom of the screen. */
export function useNotify(): Notify {
  return useContext(NoticeContext);
}
