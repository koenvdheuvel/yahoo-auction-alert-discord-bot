import { useEffect, useRef, type MouseEvent, type TouchEvent } from "react";

export type Direction = "left" | "right" | "up" | "down";
type Axis = "x" | "y";

// The finger has to move this far before the gesture picks an axis, and mostly along it.
const LOCK_DISTANCE = 10;
const LOCK_RATIO = 1.5;
// A swipe goes this far, or at least FLICK_DISTANCE at FLICK_SPEED pixels per millisecond.
const SWIPE_DISTANCE = 72;
const FLICK_DISTANCE = 24;
const FLICK_SPEED = 0.45;

interface SwipeOptions {
  /** The directions that count. A gesture along the other axis is left to the browser, for scrolling. */
  directions: Direction[];
  /** Called when the finger lifts after a long enough or fast enough move. */
  onSwipe: (direction: Direction) => void;
  /**
   * Called while the finger moves, with how far it went in a direction that counts. When the finger
   * lifts without a swipe it gets 0, to move things back. After a swipe, `onSwipe` decides what moves.
   */
  onDrag?: (offset: number, axis: Axis) => void;
  /** Return true to leave a touch alone, such as one that starts in a text field. */
  ignore?: (target: Element) => boolean;
}

// React passes touches in sheets and menus up to the component that opened them, though the
// sheet is elsewhere on the page. Only touches that start inside the element itself count.
function inside(event: TouchEvent): boolean {
  return event.target instanceof Node && event.currentTarget.contains(event.target);
}

/**
 * Touch handlers for swipes, like the ones in Discord's app: across the screen to open the list
 * of channels, or down to close a sheet. Mouse and pen input are left alone.
 */
export function useSwipe({ directions, onSwipe, onDrag, ignore }: SwipeOptions) {
  const gesture = useRef<{ x: number; y: number; time: number; axis: Axis | null; offset: number } | null>(null);

  const wanted: Record<Axis, boolean> = {
    x: directions.includes("left") || directions.includes("right"),
    y: directions.includes("up") || directions.includes("down"),
  };
  const counts = (axis: Axis, offset: number) =>
    directions.includes(axis === "x" ? (offset > 0 ? "right" : "left") : (offset > 0 ? "down" : "up"));

  return {
    onTouchStart(event: TouchEvent) {
      gesture.current = null;
      const touch = event.touches[0];
      if (event.touches.length !== 1 || !touch || !inside(event)) return;
      if (ignore && event.target instanceof Element && ignore(event.target)) return;
      gesture.current = { x: touch.clientX, y: touch.clientY, time: event.timeStamp, axis: null, offset: 0 };
    },
    onTouchMove(event: TouchEvent) {
      const current = gesture.current;
      const touch = event.touches[0];
      if (!current || !touch) return;
      const dx = touch.clientX - current.x;
      const dy = touch.clientY - current.y;
      if (current.axis === null) {
        const across = Math.abs(dx);
        const along = Math.abs(dy);
        if (across < LOCK_DISTANCE && along < LOCK_DISTANCE) return;
        const axis = across > along * LOCK_RATIO ? "x" : along > across * LOCK_RATIO ? "y" : null;
        // A move along the other axis is a scroll. A diagonal one gets a little longer to settle.
        if (axis !== null && !wanted[axis]) gesture.current = null;
        if (axis === null && Math.max(across, along) > LOCK_DISTANCE * 3) gesture.current = null;
        if (axis === null || !wanted[axis]) return;
        current.axis = axis;
      }
      const offset = current.axis === "x" ? dx : dy;
      current.offset = counts(current.axis, offset) ? offset : 0;
      onDrag?.(current.offset, current.axis);
    },
    onTouchEnd(event: TouchEvent) {
      const current = gesture.current;
      gesture.current = null;
      if (!current?.axis) return;
      const distance = Math.abs(current.offset);
      const speed = distance / Math.max(1, event.timeStamp - current.time);
      if (distance >= SWIPE_DISTANCE || (distance >= FLICK_DISTANCE && speed >= FLICK_SPEED)) {
        onSwipe(current.axis === "x" ? (current.offset > 0 ? "right" : "left") : (current.offset > 0 ? "down" : "up"));
      } else {
        onDrag?.(0, current.axis);
      }
    },
    onTouchCancel() {
      const current = gesture.current;
      gesture.current = null;
      if (current?.axis) onDrag?.(0, current.axis);
    },
  };
}

/**
 * Touches that start in a text field, or in something that scrolls sideways, belong to it and
 * not to a sideways swipe. `data-no-swipe` marks other places that need their own touches.
 */
export function ownsSidewaysTouch(target: Element): boolean {
  for (let element: Element | null = target; element && element !== document.body; element = element.parentElement) {
    if (element.matches("input, textarea, select, [contenteditable='true'], [data-no-swipe]")) return true;
    const overflow = getComputedStyle(element).overflowX;
    if ((overflow === "auto" || overflow === "scroll") && element.scrollWidth > element.clientWidth) return true;
  }
  return false;
}

const LONG_PRESS_MS = 450;

/**
 * Touch handlers that call back when a finger rests on the element, like a long press on a
 * Discord message. The tap that ends a long press does not also count as a tap.
 */
export function useLongPress(onLongPress: () => void) {
  const timer = useRef<number | undefined>(undefined);
  const origin = useRef<{ x: number; y: number } | null>(null);
  const fired = useRef(false);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const cancel = () => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    origin.current = null;
  };

  return {
    onTouchStart(event: TouchEvent) {
      cancel();
      fired.current = false;
      const touch = event.touches[0];
      if (event.touches.length !== 1 || !touch || !inside(event)) return;
      origin.current = { x: touch.clientX, y: touch.clientY };
      timer.current = window.setTimeout(() => {
        timer.current = undefined;
        fired.current = true;
        // A short buzz where the phone supports it; iPhones do not.
        if ("vibrate" in navigator) navigator.vibrate(8);
        onLongPress();
      }, LONG_PRESS_MS);
    },
    onTouchMove(event: TouchEvent) {
      const start = origin.current;
      const touch = event.touches[0];
      if (start && touch && Math.hypot(touch.clientX - start.x, touch.clientY - start.y) > LOCK_DISTANCE) cancel();
    },
    onTouchEnd(event: TouchEvent) {
      // The lifted finger would also click whatever the long press just opened under it.
      if (fired.current) event.preventDefault();
      cancel();
    },
    onTouchCancel: cancel,
    // Android opens its own menu for a long press.
    onContextMenu(event: MouseEvent) {
      if (fired.current || timer.current !== undefined) event.preventDefault();
    },
    onClickCapture(event: MouseEvent) {
      if (!fired.current) return;
      fired.current = false;
      event.preventDefault();
      event.stopPropagation();
    },
  };
}

/** Turns off the browser's own long-press behavior on touch screens: text selection and link previews. */
export const longPressable = {
  "@media (pointer: coarse)": { userSelect: "none", WebkitUserSelect: "none", WebkitTouchCallout: "none" },
} as const;
