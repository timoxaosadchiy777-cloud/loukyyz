"use client";

import { useEffect, useRef, useState } from "react";

const SYMBOLS = [
  { symbol: "BTCUSDT", label: "Bitcoin", decimals: 1 },
  { symbol: "ETHUSDT", label: "Ethereum", decimals: 2 },
  { symbol: "SOLUSDT", label: "Solana", decimals: 2 },
  { symbol: "BNBUSDT", label: "BNB", decimals: 2 },
  { symbol: "XRPUSDT", label: "XRP", decimals: 4 },
  { symbol: "DOGEUSDT", label: "Dogecoin", decimals: 5 },
] as const;

type Row = {
  symbol: string;
  label: string;
  decimals: number;
  price: number;
  prevPrice: number;
  changePct: number;
  tick: 1 | -1 | 0;
};

type BinanceTicker = {
  symbol: string;
  lastPrice: string;
  priceChangePercent: string;
};

const ENDPOINT = "https://api.binance.com/api/v3/ticker/24hr";

function fmt(n: number, decimals: number): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function Markets() {
  const [rows, setRows] = useState<Row[]>(() =>
    SYMBOLS.map((s) => ({
      symbol: s.symbol,
      label: s.label,
      decimals: s.decimals,
      price: 0,
      prevPrice: 0,
      changePct: 0,
      tick: 0,
    })),
  );
  const [status, setStatus] = useState<"loading" | "live" | "error">("loading");
  const prices = useRef<Record<string, number>>({});

  useEffect(() => {
    let alive = true;
    const query = encodeURIComponent(JSON.stringify(SYMBOLS.map((s) => s.symbol)));
    const url = `${ENDPOINT}?symbols=${query}`;

    const poll = async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as BinanceTicker[];
        if (!alive) return;

        const bySymbol = new Map(data.map((d) => [d.symbol, d]));
        setRows((prev) =>
          prev.map((row) => {
            const t = bySymbol.get(row.symbol);
            if (!t) return row;
            const price = parseFloat(t.lastPrice);
            const changePct = parseFloat(t.priceChangePercent);
            const last = prices.current[row.symbol] ?? price;
            const tick: 1 | -1 | 0 = price > last ? 1 : price < last ? -1 : 0;
            prices.current[row.symbol] = price;
            return { ...row, price, prevPrice: last, changePct, tick };
          }),
        );
        setStatus("live");
      } catch {
        if (alive) setStatus("error");
      }
    };

    poll();
    const id = setInterval(poll, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <section id="markets" className="scroll-mt-24 px-6 py-24 md:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="flex items-end justify-between gap-6 border-b border-white/10 pb-5">
          <div>
            <span className="font-mono text-[11px] uppercase tracking-[0.35em] text-[#00e676]">
              Markets
            </span>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white md:text-4xl">
              Live tape
            </h2>
          </div>
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em]">
            <span className="relative flex h-1.5 w-1.5">
              {status === "live" && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#00e676] opacity-75" />
              )}
              <span
                className={`relative inline-flex h-1.5 w-1.5 rounded-full ${
                  status === "live" ? "bg-[#00e676]" : status === "error" ? "bg-[#ef4444]" : "bg-[#f59e0b]"
                }`}
              />
            </span>
            <span className="text-[#6b7280]">
              {status === "live" ? "Live · Binance" : status === "error" ? "Offline" : "Connecting…"}
            </span>
          </div>
        </div>

        <div className="mt-8 overflow-hidden border border-white/10 bg-[#0a0a0a]">
          <div className="grid grid-cols-[1.6fr_1fr_1fr] gap-4 border-b border-white/10 px-5 py-3 font-mono text-[10px] uppercase tracking-[0.2em] text-[#6b7280]">
            <span>Instrument</span>
            <span className="text-right">Last (USDT)</span>
            <span className="text-right">24h %</span>
          </div>

          {rows.map((row) => {
            const up = row.changePct >= 0;
            const flash =
              row.tick === 1 ? "text-[#00e676]" : row.tick === -1 ? "text-[#ef4444]" : "text-white";
            return (
              <div
                key={row.symbol}
                className="grid grid-cols-[1.6fr_1fr_1fr] items-center gap-4 border-b border-white/5 px-5 py-4 last:border-0"
              >
                <div className="flex items-center gap-3">
                  <span className={`h-6 w-[2px] ${up ? "bg-[#00e676]" : "bg-[#ef4444]"}`} />
                  <div>
                    <div className="font-mono text-sm font-semibold tracking-tight text-white">
                      {row.symbol}
                    </div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#6b7280]">
                      {row.label}
                    </div>
                  </div>
                </div>

                <div className={`text-right font-mono text-sm tabular-nums transition-colors duration-300 ${flash}`}>
                  {row.price > 0 ? fmt(row.price, row.decimals) : "—"}
                </div>

                <div className="flex items-center justify-end gap-1.5 font-mono text-sm tabular-nums">
                  {row.price > 0 ? (
                    <>
                      <span className={up ? "text-[#00e676]" : "text-[#ef4444]"}>{up ? "▲" : "▼"}</span>
                      <span className={up ? "text-[#00e676]" : "text-[#ef4444]"}>
                        {up ? "+" : ""}
                        {row.changePct.toFixed(2)}%
                      </span>
                    </>
                  ) : (
                    <span className="text-[#4b5563]">—</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <p className="mt-5 font-mono text-[10px] uppercase tracking-[0.2em] text-[#4b5563]">
          {status === "error"
            ? "Не удалось подключиться к Binance · проверь соединение"
            : "Real-time spot prices · Binance public API · updates every 3s"}
        </p>
      </div>
    </section>
  );
}