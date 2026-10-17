import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLongPress, useSwipe, type Direction } from "./gestures";

function SwipeArea({ onSwipe, directions = ["right"] }: { onSwipe: (direction: Direction) => void; directions?: Direction[] }) {
  const swipe = useSwipe({ directions, onSwipe, ignore: (target) => target.tagName === "INPUT" });
  return <div data-testid="area" {...swipe}><input aria-label="Field" /></div>;
}

/** Moves one finger from the start to each point in turn, then lifts it. */
function drag(element: Element, points: [number, number][]) {
  const [first, ...rest] = points;
  fireEvent.touchStart(element, { touches: [{ clientX: first![0], clientY: first![1] }] });
  for (const [x, y] of rest) fireEvent.touchMove(element, { touches: [{ clientX: x, clientY: y }] });
  fireEvent.touchEnd(element, { touches: [] });
}

describe("useSwipe", () => {
  it("reports a long enough move along a direction that counts", () => {
    const onSwipe = vi.fn();
    render(<SwipeArea onSwipe={onSwipe} />);
    drag(screen.getByTestId("area"), [[20, 300], [40, 302], [90, 305], [140, 306]]);
    expect(onSwipe).toHaveBeenCalledWith("right");
  });

  it("leaves scrolls, other directions, short moves and text fields alone", () => {
    const onSwipe = vi.fn();
    render(<SwipeArea onSwipe={onSwipe} />);
    const area = screen.getByTestId("area");
    drag(area, [[100, 300], [104, 340], [110, 420]]);
    drag(area, [[200, 300], [150, 302], [60, 304]]);
    drag(area, [[100, 300], [112, 300], [118, 300]]);
    drag(screen.getByRole("textbox", { name: "Field" }), [[20, 300], [90, 300], [160, 300]]);
    // A move that starts as a scroll stays one, even when it turns sideways.
    drag(area, [[100, 300], [100, 330], [200, 330]]);
    expect(onSwipe).not.toHaveBeenCalled();
  });
});

function Pressable({ onLongPress, onClick }: { onLongPress: () => void; onClick: () => void }) {
  const press = useLongPress(onLongPress);
  return <button type="button" onClick={onClick} {...press}>Listing</button>;
}

describe("useLongPress", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls back when a finger rests, and the lifted finger is not also a tap", () => {
    vi.useFakeTimers();
    const onLongPress = vi.fn();
    const onClick = vi.fn();
    render(<Pressable onLongPress={onLongPress} onClick={onClick} />);
    const button = screen.getByRole("button", { name: "Listing" });

    fireEvent.touchStart(button, { touches: [{ clientX: 10, clientY: 10 }] });
    act(() => { vi.advanceTimersByTime(500); });
    fireEvent.touchEnd(button, { touches: [] });
    fireEvent.click(button);
    expect(onLongPress).toHaveBeenCalledTimes(1);
    expect(onClick).not.toHaveBeenCalled();

    // A plain tap still counts.
    fireEvent.touchStart(button, { touches: [{ clientX: 10, clientY: 10 }] });
    fireEvent.touchEnd(button, { touches: [] });
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire when the finger moves, such as when scrolling", () => {
    vi.useFakeTimers();
    const onLongPress = vi.fn();
    render(<Pressable onLongPress={onLongPress} onClick={() => undefined} />);
    const button = screen.getByRole("button", { name: "Listing" });

    fireEvent.touchStart(button, { touches: [{ clientX: 10, clientY: 10 }] });
    fireEvent.touchMove(button, { touches: [{ clientX: 10, clientY: 40 }] });
    act(() => { vi.advanceTimersByTime(500); });
    expect(onLongPress).not.toHaveBeenCalled();
  });
});
