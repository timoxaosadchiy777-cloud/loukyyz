export function Header() {
    return (
      <header className="flex justify-between items-center px-8 py-6 border-b border-white/10">
        <div className="font-mono text-emerald-400 font-bold tracking-wider">LOUKYYZ // SMC</div>
        <nav className="flex gap-6 font-mono text-sm text-neutral-400">
          <a href="#strategy" className="hover:text-emerald-400 transition">Strategy</a>
          <a href="#analytics" className="hover:text-emerald-400 transition">Analytics</a>
          <a href="#markets" className="hover:text-emerald-400 transition">Markets</a>
          <a href="#contact" className="hover:text-emerald-400 transition">Contact</a>
        </nav>
      </header>
    );
  }