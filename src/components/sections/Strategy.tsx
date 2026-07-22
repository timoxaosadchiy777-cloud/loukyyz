// src/components/sections/Strategy.tsx
"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

type Step = {
  id: string;
  phase: string;
  tag: string;
  title: string;
  summary: string;
  detail: string;
};

const STEPS: Step[] = [
  {
    id: "liquidity-sweep",
    phase: "01",
    tag: "LIQ",
    title: "Liquidity Sweep",
    summary: "Цена снимает стопы за равными хаями/лоями перед разворотом.",
    detail:
      "Стопы скапливаются на очевидных максимумах и минимумах. Крупный игрок проливает цену через эти пулы, чтобы набрать позицию против ликвидности толпы, и тут же бросает уровень. Сигнал — сам свип (прокол с быстрым возвратом в диапазон), а не пробой.",
  },
  {
    id: "choch-bos",
    phase: "02",
    tag: "MS",
    title: "CHoCH / BOS",
    summary: "CHoCH — первый признак разворота, BOS подтверждает новый тренд.",
    detail:
      "После свипа CHoCH ломает последнюю внутреннюю структуру против тренда — самое раннее свидетельство смены намерения. Следующий BOS в новом направлении подтверждает продолжение. Вместе они фиксируют переход от накопления к разгону.",
  },
  {
    id: "order-block",
    phase: "03",
    tag: "OB",
    title: "Order Block",
    summary: "Последняя противоположная свеча перед импульсом — источник движения.",
    detail:
      "После слома структуры отмечаем финальную свечу перед импульсным движением. В этом блоке остались неисполненные ордера. Цена часто возвращается его смитигировать, давая точный вход с узким инвалидом сразу за блоком.",
  },
  {
    id: "execution",
    phase: "04",
    tag: "EXE",
    title: "Execution",
    summary: "Вход на митигейшене, стоп за блоком, цель — следующий пул. R:R от 1:3.",
    detail:
      "Вход срабатывает, когда цена возвращается в order block в зоне дисконта (для лонга) или премиума (для шорта). Стоп — сразу за экстремумом блока. Цели — противоположные пулы ликвидности, минимум 1:3, риск не больше 1% на сделку.",
  },
];

export function Strategy() {
  const [active, setActive] = useState<string>(STEPS[0].id);

  return (
    <section id="strategy" className="scroll-mt-24 px-6 py-28 md:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="flex items-end justify-between gap-6 border-b border-white/10 pb-6">
          <div>
            <span className="font-mono text-xs uppercase tracking-[0.35em] text-[#00e676]">
              Methodology
            </span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white md:text-5xl">
              The SMC sequence
            </h2>
          </div>
          <span className="font-mono text-sm text-[#4b5563]">/ 01</span>
        </div>

        <div className="mt-14 grid gap-4 md:grid-cols-2">
          {STEPS.map((step, i) => {
            const isOpen = active === step.id;
            return (
              <motion.button
                key={step.id}
                type="button"
                onClick={() => setActive(isOpen ? "" : step.id)}
                initial={{ opacity: 0, y: 24 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{ duration: 0.5, delay: i * 0.05 }}
                className={`group relative overflow-hidden border p-7 text-left backdrop-blur-md transition-colors ${
                  isOpen
                    ? "border-[#00e676]/50 bg-[#00e676]/[0.04]"
                    : "border-white/10 bg-white/[0.02] hover:border-[#00e676]/30"
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-2xl font-bold text-white/10">
                      {step.phase}
                    </span>
                    <div>
                      <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#00e676]">
                        {step.tag}
                      </span>
                      <h3 className="mt-1 text-xl font-semibold tracking-tight text-white">
                        {step.title}
                      </h3>
                    </div>
                  </div>
                  <span
                    className={`font-mono text-lg text-[#94a3b8] transition-transform duration-300 ${
                      isOpen ? "rotate-45 text-[#00e676]" : ""
                    }`}
                  >
                    +
                  </span>
                </div>

                <p className="mt-4 text-sm leading-relaxed text-[#94a3b8]">
                  {step.summary}
                </p>

                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                      className="overflow-hidden"
                    >
                      <p className="mt-5 border-t border-white/10 pt-5 text-sm leading-relaxed text-[#cbd5e1]">
                        {step.detail}
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.button>
            );
          })}
        </div>
      </div>
    </section>
  );
}