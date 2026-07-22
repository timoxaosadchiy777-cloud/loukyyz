// src/lib/use-pointer.ts
"use client";

import { useEffect, useRef } from "react";

export type PointerState = {
  /** normalized -1..1 */
  x: number;
  y: number;
  /** scroll velocity, decays toward 0 */
  scrollVel: number;
};

/**
 * Shared pointer + scroll-velocity tracker, updated via a ref so R3F reads it
 * inside useFrame without triggering React re-renders.
 */
export function usePointer() {
  const state = useRef<PointerState>({ x: 0, y: 0, scrollVel: 0 });

  useEffect(() => {
    let lastScroll = window.scrollY;

    const onMove = (e: PointerEvent) => {
      state.current.x = (e.clientX / window.innerWidth) * 2 - 1;
      state.current.y = -((e.clientY / window.innerHeight) * 2 - 1);
    };
    const onScroll = () => {
      const y = window.scrollY;
      state.current.scrollVel += (y - lastScroll) * 0.01;
      lastScroll = y;
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return state;
}