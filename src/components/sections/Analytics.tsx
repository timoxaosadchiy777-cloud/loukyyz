"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  type JournalStats,
  computeStats,
  loadTrades,
  TRADES_EVENT,
} from "../../lib/journal";

export function Analytics() {
  const [stats, setStats] = useState<JournalStats | null>(null);

  useEffect(() => {
    const refresh = () => setStats(computeStats(loadTrades()));
    refresh();
    window.addEventListener(TRADES_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(TRADES_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const empty = !stats || stats.count === 0;

  const sign = (v: number) =>
    v > 0 ? "text-[#00e676]" : v < 0 ? "text-[#ef4444]" : "text-white";
  const pf =
    !stats || stats.profitFactor == null
      ? "—"
      : stats.profitFactor === Infinity
        ? "∞"
        : stats.profitFactor.toFixed(2);

  const cards = stats
    ? [
        { label: "Total R", value: `${stats.totalR > 0 ? "+" : ""}${stats.totalR.toFixed(1)}`, cls: sign(stats.totalR), big: true },
        { label: "Win rate", value: `${stats.winrate}%`, cls: "text-white" },
        { label: "Avg R", value: `${stats.avgR >= 0 ? "+" : ""}${stats.avgR.toFixed(2)}`, cls: sign(stats.avgR) },
        { label: "Profit factor", value: pf, cls: "text-white" },
        { label: "Trades", value: String(stats.count), cls: "text-white" },
        { label: "Wins / Losses", value: `${stats.wins} / ${stats.losses}`, cls: "text-white" },
        { label: "Best streak", value: stats.bestStreak ? `${stats.bestStreak}W` : "—", cls: "text-[#00e676]" },
        { label: "Worst streak", value: stats.worstStreak ? `${stats.worstStreak}L` : "—", cls: "text-[#ef4444]" },
      ]
    : [];

  return (
    <section id="analytics" className="scroll-mt-24 px-6 py-24 md:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="flex items-end justify-between gap-6 border-b border-white/10 pb-5">
          <div>
            <span className="font-mono text-[11px] uppercase tracking-[0.35em] text-[#00e676]">
              Performance
            </span>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white md:text-4xl">
              The edge, measured
            </h2>
          </div>
          <span className="font-mono text-xs text-[#4b5563]">/ 02</span>
        </div>

        {empty ? (
          <div className="mt-10 flex flex-col items-center justify-center border border-dashed border-white/10 bg-[#0a0a0a] px-6 py-20 text-center">
            <span className="font-mono text-sm text-white">Пока нет данных</span>
            <p className="mt-2 max-w-sm font-mono text-[11px] leading-relaxed text-[#4b5563]">
              Метрики считаются из журнала сделок. Добавь сделки в разделе Track
              record — статистика появится здесь автоматически.
            </p>
          </div>
        ) : (
          <div className="mt-10 grid grid-cols-2 gap-px border border-white/10 bg-white/10 md:grid-cols-4">
            {cards.map((c, i) => (
              <motion.div
                key={c.label}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.4, delay: i * 0.04 }}
                className={`flex flex-col justify-between bg-[#0a0a0a] p-6 ${c.big ? "col-span-2 md:col-span-1" : ""}`}
              >
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#6b7280]">
                  {c.label}
                </span>
                <span className={`mt-4 font-mono text-3xl font-semibold tabular-nums ${c.cls}`}>
                  {c.value}
                </span>
              </motion.div>
            ))}
          </div>
        )}

        {!empty && (
          <p className="mt-5 font-mono text-[10px] uppercase tracking-[0.2em] text-[#4b5563]">
            Live из журнала · пересчитывается при каждой сделке · результаты в R
          </p>
        )}
      </div>
    </section>
  );
}