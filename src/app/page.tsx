// src/app/page.tsx
import { SceneBackground } from "@/components/three/SceneBackground";
import { Navbar } from "@/components/layout/Navbar";
import { Hero } from "@/components/sections/Hero";
import { Strategy } from "@/components/sections/Strategy";
import { Analytics } from "@/components/sections/Analytics";
import { Markets } from "@/components/sections/Markets";
import { TrackRecord } from "@/components/sections/TrackRecord";
import { FAQ } from "@/components/sections/FAQ";
import { Contact } from "@/components/sections/Contact";
import { Footer } from "@/components/layout/Footer";

export default function Page() {
  return (
    <main className="relative min-h-screen bg-[#050505] text-white selection:bg-[#00e676] selection:text-[#050505]">
      <SceneBackground />

      <div className="relative z-10">
        <Navbar />
        <Hero />
        <Strategy />
        <Analytics />
        <Markets />
        <TrackRecord />
        <FAQ />
        <Contact />
        <Footer />
      </div>
    </main>
  );
}