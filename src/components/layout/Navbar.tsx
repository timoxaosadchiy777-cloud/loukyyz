"use client";

import Link from "next/link";

export function Navbar() {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-white/10 bg-[#050505]/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 md:px-12">
        <Link href="/" className="font-mono text-sm font-bold tracking-wider text-[#00e676]">
          SMC_CORE
        </Link>
        <nav className="hidden items-center gap-8 font-mono text-xs uppercase tracking-widest text-[#94a3b8] md:flex">
          <a href="#strategy" className="transition-colors hover:text-white">Strategy</a>
          <a href="#analytics" className="transition-colors hover:text-white">Analytics</a>
          <a href="#markets" className="transition-colors hover:text-white">Markets</a>
          <a href="#track-record" className="transition-colors hover:text-white">Track</a>
          <a href="#faq" className="transition-colors hover:text-white">FAQ</a>
        </nav>
        <a
          href="#contact"
          className="border border-[#00e676]/40 bg-[#00e676]/10 px-4 py-2 font-mono text-xs uppercase tracking-wider text-[#00e676] backdrop-blur-md transition-all hover:bg-[#00e676] hover:text-[#050505]"
        >
          Access
        </a>
      </div>
    </header>
  );
}