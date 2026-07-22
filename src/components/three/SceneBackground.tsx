"use client";

import { Canvas } from "@react-three/fiber";
import { EffectComposer, Bloom, Noise, Vignette } from "@react-three/postprocessing";
import { BlendFunction } from "postprocessing";
import { AdaptiveDpr, PerformanceMonitor } from "@react-three/drei";
import { useState } from "react";
import { LiquidityField } from "./LiquidityField";
import { usePointer } from "../../lib/use-pointer";
/**
 * Fixed full-viewport R3F background. pointer-events-none so the whole UI stays
 * interactive; the field still reads the global pointer via usePointer().
 */
export function SceneBackground() {
  const pointer = usePointer();
  const [dpr, setDpr] = useState(1.5);

  return (
    <div
      className="pointer-events-none fixed inset-0 z-0"
      aria-hidden="true"
    >
      <Canvas
        dpr={dpr}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        camera={{ position: [0, 6, 12], fov: 42 }}
      >
        {/* Drop DPR automatically when frames slip, restore when headroom returns */}
        <PerformanceMonitor
          onDecline={() => setDpr(1)}
          onIncline={() => setDpr(2)}
        />
        <AdaptiveDpr pixelated />

        <color attach="background" args={["#050505"]} />
        <fog attach="fog" args={["#050505", 10, 26]} />

        <ambientLight intensity={0.4} />
        <directionalLight position={[5, 10, 5]} intensity={0.6} />
        <pointLight position={[0, 4, 0]} intensity={2} color="#00e676" distance={20} />

        <LiquidityField pointer={pointer} />

        <EffectComposer multisampling={0}>
          <Bloom
            intensity={0.9}
            luminanceThreshold={0.2}
            luminanceSmoothing={0.9}
            mipmapBlur
          />
          <Noise premultiply blendFunction={BlendFunction.SOFT_LIGHT} opacity={0.35} />
          <Vignette eskil={false} offset={0.2} darkness={0.9} />
        </EffectComposer>
      </Canvas>

      {/* readability scrim so text sits above the field */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#050505]/70 via-[#050505]/40 to-[#050505]/90" />
    </div>
  );
}
