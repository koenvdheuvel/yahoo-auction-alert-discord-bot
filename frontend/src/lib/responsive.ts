import { useTheme } from "@mui/material/styles";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useSyncExternalStore } from "react";

/** Phones and small tablets: the searches live in a drawer and the sections in a bar at the bottom. */
export function useCompact(): boolean {
  const theme = useTheme();
  return useMediaQuery(theme.breakpoints.down("md"));
}

/** Phones: dialogs and menus open as sheets from the bottom of the screen. */
export function usePhone(): boolean {
  const theme = useTheme();
  return useMediaQuery(theme.breakpoints.down("sm"));
}

/** The main pointer is a finger, so keyboard hints do not apply and taps need room. */
export function useTouch(): boolean {
  return useMediaQuery("(pointer: coarse)");
}

/** True for fields that bring up the on-screen keyboard. */
export function isTextEntry(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false;
  if (element.isContentEditable || element.tagName === "TEXTAREA") return true;
  return element.tagName === "INPUT"
    && !["checkbox", "radio", "button", "submit", "reset", "range", "file", "color"].includes((element as HTMLInputElement).type);
}

/** How much of the page the on-screen keyboard hides at the bottom, and how far the page scrolled under the top. */
export interface KeyboardArea {
  top: number;
  bottom: number;
}

const NO_KEYBOARD: KeyboardArea = { top: 0, bottom: 0 };
let lastArea = NO_KEYBOARD;

// The on-screen keyboard shrinks the visual viewport but not the window, on iOS and Android alike.
// Zooming in shrinks it too, so the height is scaled back before deciding the keyboard is up.
function keyboardArea(): KeyboardArea {
  const viewport = window.visualViewport;
  if (!viewport || !isTextEntry(document.activeElement) || window.innerHeight - viewport.height * viewport.scale <= 150) {
    return NO_KEYBOARD;
  }
  const top = Math.round(viewport.offsetTop);
  const bottom = Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop));
  // The same numbers give the same object, so React does not render again for nothing.
  if (lastArea.top !== top || lastArea.bottom !== bottom) lastArea = { top, bottom };
  return lastArea;
}

function subscribeKeyboard(listener: () => void) {
  const viewport = window.visualViewport;
  viewport?.addEventListener("resize", listener);
  viewport?.addEventListener("scroll", listener);
  window.addEventListener("focusin", listener);
  window.addEventListener("focusout", listener);
  return () => {
    viewport?.removeEventListener("resize", listener);
    viewport?.removeEventListener("scroll", listener);
    window.removeEventListener("focusin", listener);
    window.removeEventListener("focusout", listener);
  };
}

/** Where the on-screen keyboard is, so sheets can stay above it. All zero while it is down. */
export function useKeyboardArea(): KeyboardArea {
  return useSyncExternalStore(subscribeKeyboard, keyboardArea, () => NO_KEYBOARD);
}

/** True while the on-screen keyboard is up, so bars fixed to the bottom can step aside. */
export function useKeyboardOpen(): boolean {
  return useKeyboardArea() !== NO_KEYBOARD;
}
