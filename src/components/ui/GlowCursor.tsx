"use client";
import { useEffect, useState } from "react";

export function GlowCursor() {
  const [pos, setPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handleMove = (e: MouseEvent) => setPos({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", handleMove);
    return () => window.removeEventListener("mousemove", handleMove);
  }, []);

  return (
    <div 
      className="pointer-events-none fixed w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl transition-transform duration-75 -translate-x-1/2 -translate-y-1/2 z-0"
      style={{ left: pos.x, top: pos.y }}
    />
  );
}