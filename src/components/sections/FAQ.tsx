// src/components/sections/FAQ.tsx
"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

type QA = { q: string; a: string };

const FAQ_ITEMS: QA[] = [
  {
    q: "Что такое Smart Money Concepts?",
    a: "SMC читает рынок через институциональный ордер-флоу: order blocks, свипы ликвидности, зоны премиума/дисконта и сломы структуры (BOS / CHoCH). Вместо запаздывающих индикаторов — карта того, где крупный игрок набирает и разгружает позицию.",
  },
  {
    q: "Есть ли минимальный депозит?",
    a: "Жёсткого минимума нет — методология масштабируется на любой счёт. Но сайзинг при строгом 1% на сделку осмысленно работает от нескольких сотен единиц капитала; ниже спред и минимальный лот искажают риск. Торгуй размером, где 1% — сумма, которую спокойно готов потерять.",
  },
  {
    q: "Как работает правило 1% риска?",
    a: "Каждая сделка рискует не более 1% капитала — точка. Размер позиции считается от стопа: size = (капитал × 0.01) ÷ дистанция стопа. При R:R 1:3 один профит даёт 3%, убыток стоит 1% — математика переживает длинные серии убытков.",
  },
  {
    q: "Почему так строго с риском?",
    a: "Потому что выживание компаундится, а сливы — нет. При 1% десять убытков подряд дают просадку ~10% — восстановимо. При 5% та же серия выносит ~40% и требует +67% только чтобы вернуться в ноль. Edge работает, только если ты ещё в игре.",
  },
  {
    q: "Какой винрейт ожидать?",
    a: "Подход целится в 45%+ винрейт при минимум 1:3 R:R. Убыточных сделок больше, чем ждёт новичок, и всё равно плюс: при 45% и 1:3 ожидание положительное с запасом. Работает асимметрия, а не процент попаданий.",
  },
  {
    q: "Даёте сигналы или управление счётом?",
    a: "Нет. Это аналитика и обучение: фреймворки, инструменты и прозрачный трек-рекорд. Сделки исполняешь сам на своём счёте. Ни сигнал-сервиса, ни фонда, ни обещаний доходности.",
  },
];

function Item({ item, index }: { item: QA; index: number }) {
  const [open, setOpen] = useState(false);
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.45, delay: index * 0.05 }}
      className={`border backdrop-blur-md transition-colors ${
        open
          ? "border-[#00e676]/50 bg-[#00e676]/[0.04]"
          : "border-white/10 bg-white/[0.03] hover:border-[#00e676]/30"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-6 px-6 py-5 text-left"
      >
        <span className="flex items-center gap-4">
          <span className="font-mono text-[10px] text-[#4b5563]">
            {String(index + 1).padStart(2, "0")}
          </span>
          <span className="text-sm font-medium text-white md:text-base">{item.q}</span>
        </span>
        <span
          className={`shrink-0 font-mono text-lg text-[#94a3b8] transition-transform duration-300 ${
            open ? "rotate-45 text-[#00e676]" : ""
          }`}
        >
          +
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <p className="border-t border-white/10 px-6 py-5 pl-16 text-sm leading-relaxed text-[#94a3b8]">
              {item.a}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export function FAQ() {
  return (
    <section id="faq" className="scroll-mt-24 px-6 py-28 md:px-12">
      <div className="mx-auto max-w-4xl">
        <div className="flex items-end justify-between gap-6 border-b border-white/10 pb-6">
          <div>
            <span className="font-mono text-xs uppercase tracking-[0.35em] text-[#00e676]">
              Questions
            </span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white md:text-5xl">
              Before you commit
            </h2>
          </div>
          <span className="font-mono text-sm text-[#4b5563]">/ 05</span>
        </div>

        <div className="mt-14 space-y-3">
          {FAQ_ITEMS.map((item, i) => (
            <Item key={item.q} item={item} index={i} />
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.5 }}
          className="mt-10 border border-[#f59e0b]/25 bg-[#f59e0b]/[0.04] p-6 backdrop-blur-md md:p-8"
        >
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg text-[#f59e0b]">⚠</span>
            <h3 className="font-mono text-xs uppercase tracking-[0.3em] text-[#f59e0b]">
              Risk disclaimer
            </h3>
          </div>
          <p className="mt-4 text-xs leading-relaxed text-[#94a3b8] md:text-sm">
            Торговля на форекс, фьючерсах и других инструментах с плечом несёт
            высокий уровень риска и подходит не всем инвесторам. Плечо работает как
            в вашу пользу, так и против вас. Прошлые результаты не гарантируют
            будущих — показанные трек-рекорд и винрейты историчны. Вы можете
            потерять часть или весь капитал; не торгуйте деньгами, которые не можете
            позволить себе потерять. Материал носит образовательный и аналитический
            характер и не является финансовой рекомендацией. Все торговые решения вы
            принимаете самостоятельно.
          </p>
        </motion.div>
      </div>
    </section>
  );
}