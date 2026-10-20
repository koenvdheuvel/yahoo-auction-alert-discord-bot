import { fireEvent } from "@testing-library/react";
import { vi } from "vitest";

interface ScreenOptions {
  /** A finger for a pointer, which cannot hover. Screens under 900 pixels wide have one unless told otherwise. */
  touch?: boolean;
  reducedMotion?: boolean;
}

/**
 * Makes media queries answer as they would on a screen this wide, so components pick their phone or
 * desktop layout. jsdom has no matchMedia, which MUI takes for a wide screen with a mouse. Undo it with
 * `vi.unstubAllGlobals()`.
 */
export function setScreen(width: number, { touch = width < 900, reducedMotion = false }: ScreenOptions = {}) {
  vi.stubGlobal("matchMedia", (query: string) => {
    const max = /max-width:\s*([\d.]+)px/.exec(query);
    const min = /min-width:\s*([\d.]+)px/.exec(query);
    const matches = /pointer:\s*coarse|hover:\s*none/.test(query) ? touch
      : /pointer:\s*fine|hover:\s*hover/.test(query) ? !touch
      : query.includes("prefers-reduced-motion") ? reducedMotion
      // Other preferences, such as the color scheme, stay at the browser's defaults.
      : query.includes("prefers-") ? false
      : (!max || width <= Number(max[1])) && (!min || width >= Number(min[1]));
    return { matches, media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined,
      addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false };
  });
}

/** A phone, 390 pixels wide, with a finger for a pointer. */
export function setPhone(options: ScreenOptions = {}) {
  setScreen(390, options);
}

/** Acts as if the on-screen keyboard covers the bottom of the screen whenever a text field has focus. */
export function showKeyboard() {
  vi.stubGlobal("visualViewport", { height: 300, scale: 1, offsetTop: 0, addEventListener: () => undefined,
    removeEventListener: () => undefined });
}

/** Moves one finger from the start to each point in turn, then lifts it. */
export function drag(element: Element, points: [number, number][]) {
  const [first, ...rest] = points;
  fireEvent.touchStart(element, { touches: [{ clientX: first![0], clientY: first![1] }] });
  for (const [x, y] of rest) fireEvent.touchMove(element, { touches: [{ clientX: x, clientY: y }] });
  fireEvent.touchEnd(element, { touches: [] });
}
