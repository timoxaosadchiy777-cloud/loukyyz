// src/components/three/LiquidityField.tsx
"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { PointerState } from "../../lib/use-pointer";

const ACCENT = new THREE.Color("#00e676");
const COOL = new THREE.Color("#0a3d2c");
const DEEP = new THREE.Color("#041b12");

type Props = {
  pointer: React.MutableRefObject<PointerState>;
  cols?: number;
  rows?: number;
};

export function LiquidityField({ pointer, cols = 56, rows = 32 }: Props) {
  const mesh = useRef<THREE.InstancedMesh>(null!);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const count = cols * rows;

  const layout = useMemo(() => {
    const gap = 0.42;
    const positions = new Float32Array(count * 2);
    let i = 0;
    for (let x = 0; x < cols; x++) {
      for (let z = 0; z < rows; z++) {
        positions[i++] = (x - cols / 2) * gap;
        positions[i++] = (z - rows / 2) * gap;
      }
    }
    return { positions, gap };
  }, [cols, rows, count]);

  const colorArray = useMemo(() => new Float32Array(count * 3), [count]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const p = pointer.current;
    p.scrollVel *= 0.9;

    // slow camera drift so the scene never sits still
    state.camera.position.x = Math.sin(t * 0.12) * 1.6;
    state.camera.position.y = 6 + Math.sin(t * 0.18) * 0.5;
    state.camera.lookAt(0, -1, 0);

    const mx = p.x * (cols * layout.gap) * 0.5;
    const mz = -p.y * (rows * layout.gap) * 0.5;

    for (let i = 0; i < count; i++) {
      const px = layout.positions[i * 2];
      const pz = layout.positions[i * 2 + 1];

      // layered travelling waves — the "breathing" of the whole grid
      const distC = Math.hypot(px, pz);
      const wave =
        Math.sin(px * 0.35 + t * 1.1) * 0.4 +
        Math.cos(pz * 0.4 - t * 0.85) * 0.4 +
        Math.sin(distC * 0.5 - t * 1.6) * 0.5; // concentric ripple from center

      const dist = Math.hypot(px - mx, pz - mz);
      const pointerLift = Math.max(0, 2.0 - dist * 0.22) * 1.0;
      const scrollLift = Math.sin(dist * 0.4 - t * 4) * p.scrollVel * 0.6;

      const h = 0.12 + Math.abs(wave) + pointerLift + Math.abs(scrollLift);

      dummy.position.set(px, h / 2 - 1.5, pz);
      dummy.scale.set(0.12, h, 0.12);
      dummy.updateMatrix();
      mesh.current.setMatrixAt(i, dummy.matrix);

      // color: deep valleys → cool mids → hot emerald ridges
      const heat = Math.min(1, (Math.abs(wave) - 0.2) * 0.6 + pointerLift * 0.5 + Math.abs(scrollLift));
      const base = DEEP.clone().lerp(COOL, Math.min(1, Math.abs(wave)));
      const c = base.lerp(ACCENT, Math.max(0, heat));
      colorArray[i * 3] = c.r;
      colorArray[i * 3 + 1] = c.g;
      colorArray[i * 3 + 2] = c.b;
    }

    mesh.current.instanceMatrix.needsUpdate = true;
    const attr = mesh.current.geometry.getAttribute("color");
    if (attr) (attr as THREE.InstancedBufferAttribute).needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={mesh}
      args={[undefined, undefined, count]}
      frustumCulled={false}
    >
      <boxGeometry args={[1, 1, 1]}>
        <instancedBufferAttribute attach="attributes-color" args={[colorArray, 3]} />
      </boxGeometry>
      <meshStandardMaterial
        vertexColors
        emissive={ACCENT}
        emissiveIntensity={0.7}
        roughness={0.3}
        metalness={0.1}
        toneMapped={false}
      />
    </instancedMesh>
  );
}