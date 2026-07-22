// src/components/sections/Contact.tsx
"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

type Errors = Partial<Record<"name" | "email" | "capital" | "message", string>>;
type Status = "idle" | "submitting" | "done";

const CAPITAL_TIERS = ["< $10k", "$10k – $50k", "$50k – $250k", "$250k+"];

export function Contact() {
  const [form, setForm] = useState({ name: "", email: "", capital: "", message: "" });
  const [errors, setErrors] = useState<Errors>({});
  const [status, setStatus] = useState<Status>("idle");

  const set = (k: keyof typeof form, v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setErrors((e) => ({ ...e, [k]: undefined }));
  };

  const validate = (): boolean => {
    const next: Errors = {};
    if (form.name.trim().length < 2) next.name = "Укажи имя";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) next.email = "Некорректный email";
    if (!form.capital) next.capital = "Выбери тир";
    if (form.message.trim().length < 10) next.message = "Расскажи чуть подробнее (10+ символов)";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const submit = () => {
    if (status === "submitting") return;
    if (!validate()) return;
    setStatus("submitting");
    // Симуляция отправки — заменишь на свой endpoint / server action.
    setTimeout(() => setStatus("done"), 1400);
  };

  const field =
    "w-full border bg-white/[0.02] px-4 py-3 font-mono text-sm text-white outline-none transition-colors placeholder:text-[#4b5563] focus:border-[#00e676]/60";

  return (
    <section id="contact" className="scroll-mt-24 px-6 py-28 md:px-12">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end justify-between gap-6 border-b border-white/10 pb-6">
          <div>
            <span className="font-mono text-xs uppercase tracking-[0.35em] text-[#00e676]">
              Terminal
            </span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white md:text-5xl">
              Open a desk
            </h2>
          </div>
          <span className="font-mono text-sm text-[#4b5563]">/ 06</span>
        </div>

        <div className="mt-14 border border-[#00e676]/15 bg-white/[0.03] p-7 backdrop-blur-md md:p-10">
          <AnimatePresence mode="wait">
            {status === "done" ? (
              <motion.div
                key="done"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center py-10 text-center"
              >
                <div className="flex h-14 w-14 items-center justify-center rounded-full border border-[#00e676] text-2xl text-[#00e676]">
                  ✓
                </div>
                <h3 className="mt-6 text-xl font-semibold text-white">Заявка принята</h3>
                <p className="mt-2 font-mono text-sm text-[#94a3b8]">
                  Свяжемся по {form.email} в течение сессии.
                </p>
              </motion.div>
            ) : (
              <motion.div
                key="form"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="space-y-5"
              >
                <div className="grid gap-5 md:grid-cols-2">
                  <div>
                    <label className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#94a3b8]">
                      Имя
                    </label>
                    <input
                      value={form.name}
                      onChange={(e) => set("name", e.target.value)}
                      placeholder="Александр"
                      className={`mt-2 ${field} ${errors.name ? "border-[#ef4444]" : "border-white/10"}`}
                    />
                    {errors.name && (
                      <p className="mt-1.5 font-mono text-[10px] text-[#ef4444]">{errors.name}</p>
                    )}
                  </div>

                  <div>
                    <label className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#94a3b8]">
                      Email
                    </label>
                    <input
                      value={form.email}
                      onChange={(e) => set("email", e.target.value)}
                      placeholder="you@fund.com"
                      className={`mt-2 ${field} ${errors.email ? "border-[#ef4444]" : "border-white/10"}`}
                    />
                    {errors.email && (
                      <p className="mt-1.5 font-mono text-[10px] text-[#ef4444]">{errors.email}</p>
                    )}
                  </div>
                </div>

                <div>
                  <label className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#94a3b8]">
                    Размер капитала
                  </label>
                  <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
                    {CAPITAL_TIERS.map((tier) => (
                      <button
                        key={tier}
                        type="button"
                        onClick={() => set("capital", tier)}
                        className={`border px-3 py-2.5 font-mono text-[11px] transition-colors ${
                          form.capital === tier
                            ? "border-[#00e676] bg-[#00e676]/10 text-[#00e676]"
                            : "border-white/10 text-[#94a3b8] hover:border-[#00e676]/40"
                        }`}
                      >
                        {tier}
                      </button>
                    ))}
                  </div>
                  {errors.capital && (
                    <p className="mt-1.5 font-mono text-[10px] text-[#ef4444]">{errors.capital}</p>
                  )}
                </div>

                <div>
                  <label className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#94a3b8]">
                    Кратко
                  </label>
                  <textarea
                    value={form.message}
                    onChange={(e) => set("message", e.target.value)}
                    rows={4}
                    placeholder="Что торгуешь и где хочешь получить edge?"
                    className={`mt-2 resize-none ${field} ${errors.message ? "border-[#ef4444]" : "border-white/10"}`}
                  />
                  {errors.message && (
                    <p className="mt-1.5 font-mono text-[10px] text-[#ef4444]">{errors.message}</p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={submit}
                  disabled={status === "submitting"}
                  className="group relative w-full overflow-hidden border border-[#00e676] bg-[#00e676]/[0.06] px-8 py-4 font-mono text-xs font-semibold uppercase tracking-[0.2em] text-[#00e676] transition-colors hover:text-[#050505] disabled:cursor-wait"
                >
                  <span className="absolute inset-0 origin-left scale-x-0 bg-[#00e676] transition-transform duration-300 ease-out group-hover:scale-x-100" />
                  <span className="relative z-10">
                    {status === "submitting" ? "Отправляю…" : "Отправить заявку →"}
                  </span>
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}