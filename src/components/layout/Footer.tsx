export function Footer() {
    return (
      <footer className="border-t border-white/10 bg-[#050505] px-6 py-12 md:px-12">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-6 md:flex-row">
          <span className="font-mono text-xs text-[#94a3b8]">
            © {new Date().getFullYear()} SMC Frameworks. All rights reserved.
          </span>
          <div className="flex items-center gap-6 font-mono text-xs text-[#94a3b8]">
            <a href="#strategy" className="hover:text-[#00e676]">Strategy</a>
            <a href="#track-record" className="hover:text-[#00e676]">Track Record</a>
            <a href="#faq" className="hover:text-[#00e676]">FAQ</a>
          </div>
        </div>
      </footer>
    );
  }