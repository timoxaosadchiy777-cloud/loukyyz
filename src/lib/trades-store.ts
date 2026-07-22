// src/lib/trades-store.ts
export type Result = "WIN" | "LOSS";
export type Trade = {
  id: string;
  date: string;
  pair: string;
  side: "LONG" | "SHORT";
  setup: string;
  rr: number;
  result: Result;
};

export const INITIAL_TRADES: Trade[] = [
  { id: "T-101", date: "2026-07-22", pair: "XAU/USD", side: "LONG", setup: "OB + Sweep", rr: 3.5, result: "WIN" },
];

export function getStoredTrades(): Trade[] {
  if (typeof window === "undefined") return INITIAL_TRADES;
  const saved = localStorage.getItem("smc_trades");
  if (!saved) {
    localStorage.setItem("smc_trades", JSON.stringify(INITIAL_TRADES));
    return INITIAL_TRADES;
  }
  try {
    return JSON.parse(saved);
  } catch {
    return INITIAL_TRADES;
  }
}

export function saveTrade(newTradeData: Omit<Trade, "id">) {
  if (typeof window === "undefined") return;
  const trades = getStoredTrades();
  const nextId = `T-${100 + trades.length + 1}`;
  const trade: Trade = { id: nextId, ...newTradeData };
  const updated = [trade, ...trades];
  localStorage.setItem("smc_trades", JSON.stringify(updated));
  window.dispatchEvent(new Event("storage"));
}