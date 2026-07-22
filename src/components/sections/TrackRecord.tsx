// src/components/sections/TrackRecord.tsx
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  type Trade,
  type Direction,
  PSYCH_TAGS,
  loadTrades,
  saveTrades,
  computeStats,
  newestFirst,
  equityPoints,
  equityPaths,
  zeroBaselineY,
  resizeImage,
} from "../../lib/journal";

type Filter = "ALL" | "WIN" | "LOSS";

const EMPTY_FORM = {
  date: new Date().toISOString().slice(0, 10),
  pair: "",
  tf: "",
  setup: "",
  dir: "long" as Direction,
  r: "",
  risk: "",
  commission: "",
  noteShort: "",
  notes: "",
};

export function TrackRecord() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [lightbox, setLightbox] = useState<{ src: string; label: string } | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const [form, setForm] = useState(EMPTY_FORM);
  const [tags, setTags] = useState<Set<string>>(new Set());
  const [shots, setShots] = useState<{ before: string | null; after: string | null }>({ before: null, after: null });
  const [error, setError] = useState<string | null>(null);

  const beforeInput = useRef<HTMLInputElement>(null);
  const afterInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTrades(loadTrades());
    setHydrated(true);
  }, []);
  useEffect(() => {
    if (hydrated) saveTrades(trades);
  }, [trades, hydrated]);

  const stats = useMemo(() => computeStats(trades), [trades]);
  const points = useMemo(() => equityPoints(trades), [trades]);
  const eqPaths = useMemo(() => equityPaths(points, 600, 120), [points]);
  const baselineY = useMemo(() => zeroBaselineY(points, 120), [points]);

  const visible = useMemo(() => {
    const sorted = newestFirst(trades);
    if (filter === "ALL") return sorted;
    return sorted.filter((t) => (filter === "WIN" ? t.r > 0 : t.r <= 0));
  }, [trades, filter]);

  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const toggleTag = (tag: string) =>
    setTags((prev) => {
      const next = new Set(prev);
      next.has(tag) ? next.delete(tag) : next.add(tag);
      return next;
    });

  const onFile = async (which: "before" | "after", file?: File) => {
    if (!file) return;
    const dataUrl = await resizeImage(file);
    setShots((s) => ({ ...s, [which]: dataUrl }));
  };

  const addTrade = () => {
    const r = parseFloat(form.r);
    if (isNaN(r)) {
      setError("Укажи результат в R (например 2 или -1)");
      return;
    }
    const risk = parseFloat(form.risk);
    const commission = parseFloat(form.commission);
    const trade: Trade = {
      id: Date.now(),
      date: form.date || new Date().toISOString().slice(0, 10),
      pair: form.pair.trim().toUpperCase() || "—",
      tf: form.tf.trim() || "—",
      setup: form.setup.trim() || "—",
      dir: form.dir,
      r,
      risk: isNaN(risk) ? null : risk,
      commission: isNaN(commission) ? null : commission,
      noteShort: form.noteShort.trim(),
      notes: form.notes.trim(),
      tags: Array.from(tags),
      before: shots.before,
      after: shots.after,
    };
    setTrades((prev) => [...prev, trade]);
    setForm({ ...EMPTY_FORM, date: form.date });
    setTags(new Set());
    setShots({ before: null, after: null });
    if (beforeInput.current) beforeInput.current.value = "";
    if (afterInput.current) afterInput.current.value = "";
    setError(null);
  };

  const removeTrade = (id: number) => setTrades((prev) => prev.filter((t) => t.id !== id));
  const clearAll = () => {
    if (typeof window !== "undefined" && window.confirm("Удалить все сделки?")) setTrades([]);
  };

  const field =
    "w-full border border-white/10 bg-[#050505] px-3 py-2.5 font-mono text-sm text-white outline-none transition-colors placeholder:text-[#4b5563] focus:border-[#00e676]/50";
  const lbl = "mb-1.5 block font-mono text-[10px] uppercase tracking-[0.15em] text-[#6b7280]";
  const sign = (v: number) => (v > 0 ? "text-[#00e676]" : v < 0 ? "text-[#ef4444]" : "text-white");
  const pf =
    stats.profitFactor == null
      ? "—"
      : stats.profitFactor === Infinity
        ? "∞"
        : stats.profitFactor.toFixed(2);

  return (
    <section id="track-record" className="scroll-mt-24 px-6 py-24 md:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="flex items-end justify-between gap-6 border-b border-white/10 pb-5">
          <div>
            <span className="font-mono text-[11px] uppercase tracking-[0.35em] text-[#00e676]">
              Ledger
            </span>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white md:text-4xl">
              Track record
            </h2>
          </div>
          <span className="font-mono text-xs text-[#4b5563]">/ 04</span>
        </div>

        <div className="mt-8 grid gap-px border border-white/10 bg-white/10 lg:grid-cols-[1.4fr_1fr]">
          <div className="bg-[#0a0a0a] p-6">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#6b7280]">
                Equity curve · R
              </span>
              <span className={`font-mono text-lg font-semibold tabular-nums ${sign(stats.totalR)}`}>
                {stats.totalR > 0 ? "+" : ""}
                {stats.totalR.toFixed(1)}R
              </span>
            </div>

            <div className="mt-4 h-[120px] w-full">
              {eqPaths ? (
                <svg viewBox="0 0 600 120" preserveAspectRatio="none" className="h-full w-full">
                  <defs>
                    <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={eqPaths.last >= 0 ? "#00e676" : "#ef4444"} stopOpacity="0.18" />
                      <stop offset="100%" stopColor={eqPaths.last >= 0 ? "#00e676" : "#ef4444"} stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  {baselineY != null && (
                    <line x1="0" y1={baselineY} x2="600" y2={baselineY} stroke="#ffffff" strokeOpacity="0.12" strokeDasharray="3 5" />
                  )}
                  <motion.path key={eqPaths.fill} d={eqPaths.fill} fill="url(#eq)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }} />
                  <motion.path
                    key={eqPaths.line}
                    d={eqPaths.line}
                    fill="none"
                    stroke={eqPaths.last >= 0 ? "#00e676" : "#ef4444"}
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{ duration: 0.7, ease: "easeInOut" }}
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
              ) : (
                <div className="flex h-full flex-col items-center justify-center border border-dashed border-white/10">
                  <span className="font-mono text-xs text-[#4b5563]">Нет данных</span>
                  <span className="mt-1 font-mono text-[10px] text-[#3a3f47]">Добавь сделку — график построится сам</span>
                </div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-px bg-white/10">
            {[
              { label: "Winrate", value: `${stats.winrate}%`, cls: "text-white" },
              { label: "Trades", value: String(stats.count), cls: "text-white" },
              { label: "Avg R", value: `${stats.avgR >= 0 ? "+" : ""}${stats.avgR.toFixed(2)}`, cls: sign(stats.avgR) },
              { label: "Profit factor", value: pf, cls: "text-white" },
              { label: "Streak", value: stats.streak, cls: stats.streak.startsWith("+") ? "text-[#00e676]" : stats.streak === "—" ? "text-white" : "text-[#ef4444]" },
              { label: "W / L", value: `${stats.wins} / ${stats.losses}`, cls: "text-white" },
            ].map((s) => (
              <div key={s.label} className="flex flex-col justify-between bg-[#0a0a0a] p-5">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#6b7280]">{s.label}</span>
                <span className={`mt-3 font-mono text-2xl font-semibold tabular-nums ${s.cls}`}>{s.value}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
          <div className="inline-flex border border-white/10 bg-[#0a0a0a]">
            {(["ALL", "WIN", "LOSS"] as Filter[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`border-r border-white/10 px-5 py-2.5 font-mono text-[11px] uppercase tracking-[0.2em] transition-colors last:border-0 ${
                  filter === f ? "bg-[#00e676] text-[#050505]" : "text-[#94a3b8] hover:text-white"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setFormOpen((v) => !v)}
              className="border border-[#00e676]/50 px-5 py-2.5 font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-[#00e676] transition-colors hover:bg-[#00e676] hover:text-[#050505]"
            >
              {formOpen ? "Закрыть" : "+ Сделка"}
            </button>
            {trades.length > 0 && (
              <button
                type="button"
                onClick={clearAll}
                className="border border-white/10 px-5 py-2.5 font-mono text-[11px] uppercase tracking-[0.2em] text-[#6b7280] transition-colors hover:border-[#ef4444]/50 hover:text-[#ef4444]"
              >
                Очистить
              </button>
            )}
          </div>
        </div>

        <AnimatePresence initial={false}>
          {formOpen && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }} className="overflow-hidden">
              <div className="mt-4 border border-white/10 bg-[#0a0a0a] p-6">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                  <div><label className={lbl}>Дата</label><input type="date" value={form.date} onChange={(e) => set("date", e.target.value)} className={field} /></div>
                  <div><label className={lbl}>Пара</label><input value={form.pair} onChange={(e) => set("pair", e.target.value)} placeholder="EURUSD" className={field} /></div>
                  <div><label className={lbl}>TF</label><input value={form.tf} onChange={(e) => set("tf", e.target.value)} placeholder="H4" className={field} /></div>
                  <div><label className={lbl}>Сетап</label><input value={form.setup} onChange={(e) => set("setup", e.target.value)} placeholder="OB + Sweep" className={field} /></div>
                  <div><label className={lbl}>Напр.</label><select value={form.dir} onChange={(e) => set("dir", e.target.value)} className={field}><option value="long">Long</option><option value="short">Short</option></select></div>
                  <div><label className={lbl}>R</label><input value={form.r} onChange={(e) => set("r", e.target.value)} type="number" step="0.1" placeholder="2 / -1" className={field} /></div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                  <div><label className={lbl}>Риск %</label><input value={form.risk} onChange={(e) => set("risk", e.target.value)} type="number" step="0.1" placeholder="1.0" className={field} /></div>
                  <div><label className={lbl}>Комиссия $</label><input value={form.commission} onChange={(e) => set("commission", e.target.value)} type="number" step="0.01" placeholder="0.5" className={field} /></div>
                  <div className="col-span-2"><label className={lbl}>Причина входа</label><input value={form.noteShort} onChange={(e) => set("noteShort", e.target.value)} placeholder="Кратко" className={field} /></div>
                </div>

                <div className="mt-4">
                  <label className={lbl}>Состояние</label>
                  <div className="flex flex-wrap gap-2">
                    {PSYCH_TAGS.map((tag) => {
                      const on = tags.has(tag);
                      return (
                        <button key={tag} type="button" onClick={() => toggleTag(tag)} className={`border px-3 py-1.5 font-mono text-xs transition-colors ${on ? "border-[#00e676] text-[#00e676]" : "border-white/10 text-[#6b7280] hover:border-white/25"}`}>{tag}</button>
                      );
                    })}
                  </div>
                </div>

                <div className="mt-4"><label className={lbl}>Заметка</label><textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={2} placeholder="Логика сделки…" className={`${field} resize-y`} /></div>

                <div className="mt-4 grid grid-cols-2 gap-3">
                  {(["before", "after"] as const).map((which) => (
                    <div key={which}>
                      <label className={lbl}>Скрин {which === "before" ? "до" : "после"}</label>
                      <div onClick={() => (which === "before" ? beforeInput : afterInput).current?.click()} className="relative flex min-h-[80px] cursor-pointer items-center justify-center overflow-hidden border border-dashed border-white/15 bg-[#050505] transition-colors hover:border-[#00e676]/50">
                        {shots[which] ? (
                          <>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={shots[which]!} alt="" className="h-[80px] w-full object-cover" />
                            <button type="button" onClick={(e) => { e.stopPropagation(); setShots((s) => ({ ...s, [which]: null })); const inp = which === "before" ? beforeInput : afterInput; if (inp.current) inp.current.value = ""; }} className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#050505]/80 text-xs text-white">✕</button>
                          </>
                        ) : (
                          <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#4b5563]">Прикрепить</span>
                        )}
                        <input ref={which === "before" ? beforeInput : afterInput} type="file" accept="image/*" className="hidden" onChange={(e) => onFile(which, e.target.files?.[0])} />
                      </div>
                    </div>
                  ))}
                </div>

                {error && <p className="mt-4 font-mono text-xs text-[#ef4444]">{error}</p>}

                <button type="button" onClick={addTrade} className="mt-5 border border-[#00e676] bg-[#00e676] px-6 py-3 font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-[#050505] transition-opacity hover:opacity-90">
                  Записать сделку
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="mt-6 overflow-hidden border border-white/10 bg-[#0a0a0a]">
          <div className="hidden grid-cols-[auto_1fr_1fr_0.7fr_1.2fr_0.7fr_0.7fr_0.8fr_auto] gap-4 border-b border-white/10 px-5 py-3 font-mono text-[10px] uppercase tracking-[0.15em] text-[#6b7280] md:grid">
            <span></span><span>Date</span><span>Pair</span><span>TF</span><span>Setup</span><span>Dir</span><span>Risk</span><span className="text-right">R</span><span></span>
          </div>

          {visible.length === 0 ? (
            <div className="px-5 py-16 text-center">
              <div className="font-mono text-sm text-white">{trades.length === 0 ? "Журнал пуст" : "Нет сделок под фильтр"}</div>
              <p className="mt-2 font-mono text-[11px] text-[#4b5563]">{trades.length === 0 ? "Нажми «+ Сделка» — статистика посчитается сама" : "Смени фильтр выше"}</p>
            </div>
          ) : (
            <AnimatePresence mode="popLayout">
              {visible.map((t) => {
                const win = t.r > 0;
                const open = expanded === t.id;
                return (
                  <motion.div key={t.id} layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} className="border-b border-white/5 last:border-0">
                    <div onClick={() => setExpanded(open ? null : t.id)} className="grid cursor-pointer grid-cols-2 items-center gap-4 px-5 py-3.5 font-mono text-sm transition-colors hover:bg-white/[0.03] md:grid-cols-[auto_1fr_1fr_0.7fr_1.2fr_0.7fr_0.7fr_0.8fr_auto]">
                      <span className={`inline-block h-4 w-[3px] ${win ? "bg-[#00e676]" : "bg-[#ef4444]"}`} />
                      <span className="text-[#94a3b8] tabular-nums">{t.date}</span>
                      <span className="font-semibold text-white">{t.pair}</span>
                      <span className="text-[#6b7280]">{t.tf}</span>
                      <span className="text-[#cbd5e1]">{t.setup}</span>
                      <span className={t.dir === "long" ? "text-[#00e676]" : "text-[#f59e0b]"}>{t.dir === "long" ? "Long" : "Short"}</span>
                      <span className="text-[#6b7280] tabular-nums">{t.risk != null ? `${t.risk}%` : "—"}</span>
                      <span className={`text-right font-semibold tabular-nums ${win ? "text-[#00e676]" : "text-[#ef4444]"}`}>{t.r > 0 ? "+" : ""}{t.r}R</span>
                      <button type="button" onClick={(e) => { e.stopPropagation(); removeTrade(t.id); }} className="text-[#4b5563] transition-colors hover:text-[#ef4444]">✕</button>
                    </div>

                    <AnimatePresence initial={false}>
                      {open && (
                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }} className="overflow-hidden bg-[#050505]">
                          <div className="flex flex-wrap gap-8 px-5 py-5 text-sm">
                            <div><div className={lbl}>Комиссия</div><div className="mt-1 font-mono text-white">{t.commission != null ? `$${t.commission}` : "—"}</div></div>
                            <div className="max-w-xs"><div className={lbl}>Состояние</div><div className="mt-1 flex flex-wrap gap-1.5">{t.tags.length ? t.tags.map((tag) => <span key={tag} className="border border-[#00e676]/30 px-2 py-0.5 font-mono text-[10px] text-[#00e676]">{tag}</span>) : <span className="text-[#4b5563]">—</span>}</div></div>
                            <div className="max-w-md flex-1"><div className={lbl}>Причина входа</div><div className="mt-1 text-[#cbd5e1]">{t.noteShort || "—"}</div>{t.notes && <div className="mt-3 whitespace-pre-line text-[#94a3b8]">{t.notes}</div>}</div>
                            {(t.before || t.after) && (
                              <div className="flex gap-2">
                                {t.before && (
                                  // eslint-disable-next-line @next/next/no-img-element
                                  <img src={t.before} alt="до" onClick={() => setLightbox({ src: t.before!, label: `До — ${t.pair}` })} className="h-16 w-16 cursor-pointer border border-white/10 object-cover" />
                                )}
                                {t.after && (
                                  // eslint-disable-next-line @next/next/no-img-element
                                  <img src={t.after} alt="после" onClick={() => setLightbox({ src: t.after!, label: `После — ${t.pair}` })} className="h-16 w-16 cursor-pointer border border-white/10 object-cover" />
                                )}
                              </div>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          )}
        </div>

        <p className="mt-5 font-mono text-[10px] uppercase tracking-[0.2em] text-[#4b5563]">
          Данные хранятся локально в браузере · результаты в R · past performance ≠ future results
        </p>
      </div>

      <AnimatePresence>
        {lightbox && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setLightbox(null)} className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-[#050505]/92 p-8">
            <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-[#6b7280]">{lightbox.label}</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={lightbox.src} alt="" className="max-h-[75vh] max-w-[90vw] border border-white/10" onClick={(e) => e.stopPropagation()} />
            <button type="button" onClick={() => setLightbox(null)} className="absolute right-7 top-6 flex h-9 w-9 items-center justify-center border border-white/10 text-white">✕</button>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}