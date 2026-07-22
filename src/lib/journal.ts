// src/lib/journal.ts
export type Direction = "long" | "short";

export type Trade = {
  id: number;
  date: string;
  pair: string;
  tf: string;
  setup: string;
  dir: Direction;
  r: number;
  risk: number | null;
  commission: number | null;
  noteShort: string;
  notes: string;
  tags: string[];
  before: string | null;
  after: string | null;
};

export type JournalStats = {
  count: number;
  wins: number;
  losses: number;
  winrate: number;
  totalR: number;
  avgR: number;
  avgRisk: number | null;
  bestStreak: number;
  worstStreak: number;
  streak: string;
  profitFactor: number | null;
};

export const PSYCH_TAGS = [
  "✅ По плану",
  "🧘 Дисциплина",
  "⚡ FOMO",
  "🔥 Тильт",
  "🤔 Неуверенность",
  "⏳ Пересидел",
  "🏃 Ранний выход",
] as const;

const STORAGE_KEY = "trades";

function chronological(trades: Trade[]): Trade[] {
  return [...trades].sort(
    (a, b) => (a.date > b.date ? 1 : a.date < b.date ? -1 : a.id - b.id),
  );
}

export function newestFirst(trades: Trade[]): Trade[] {
  return [...trades].sort(
    (a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id),
  );
}

export function computeStats(trades: Trade[]): JournalStats {
  const count = trades.length;
  const wins = trades.filter((t) => t.r > 0).length;
  const losses = count - wins;
  const winrate = count ? Math.round((wins / count) * 100) : 0;
  const totalR = trades.reduce((s, t) => s + t.r, 0);
  const avgR = count ? totalR / count : 0;

  const risksKnown = trades.filter((t) => t.risk != null) as (Trade & { risk: number })[];
  const avgRisk = risksKnown.length
    ? risksKnown.reduce((s, t) => s + t.risk, 0) / risksKnown.length
    : null;

  const grossWin = trades.filter((t) => t.r > 0).reduce((s, t) => s + t.r, 0);
  const grossLoss = Math.abs(trades.filter((t) => t.r < 0).reduce((s, t) => s + t.r, 0));
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : null;

  const { best, worst, current } = streaks(trades);

  return {
    count, wins, losses, winrate, totalR, avgR, avgRisk,
    bestStreak: best, worstStreak: worst, streak: current, profitFactor,
  };
}

function streaks(trades: Trade[]): { best: number; worst: number; current: string } {
  if (!trades.length) return { best: 0, worst: 0, current: "—" };
  const sorted = chronological(trades);

  let best = 0, worst = 0, run = 0;
  let runDir: boolean | null = null;
  for (const t of sorted) {
    const win = t.r > 0;
    if (runDir === null || win === runDir) {
      run = runDir === null ? 1 : run + 1;
      runDir = win;
    } else {
      run = 1;
      runDir = win;
    }
    if (win) best = Math.max(best, run);
    else worst = Math.max(worst, run);
  }

  let cur = 0;
  let dir: boolean | null = null;
  for (let i = sorted.length - 1; i >= 0; i--) {
    const win = sorted[i].r > 0;
    if (dir === null) { dir = win; cur = 1; }
    else if (win === dir) cur++;
    else break;
  }
  return { best, worst, current: (dir ? "+" : "−") + cur };
}

export function equityPoints(trades: Trade[]): number[] {
  const sorted = chronological(trades);
  let cum = 0;
  const points = [0];
  sorted.forEach((t) => { cum += t.r; points.push(cum); });
  return points;
}

export function equityPaths(
  points: number[], w = 600, h = 120, pad = 4,
): { line: string; fill: string; last: number; min: number; max: number } | null {
  if (points.length < 2) return null;
  const min = Math.min(...points, 0);
  const max = Math.max(...points, 0);
  const range = max - min || 1;
  const stepX = (w - 2 * pad) / (points.length - 1 || 1);
  const coords = points.map((v, i) => {
    const x = pad + i * stepX;
    const y = h - pad - ((v - min) / range) * (h - 2 * pad);
    return [x, y] as const;
  });
  const line = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c[0].toFixed(2)},${c[1].toFixed(2)}`).join(" ");
  const fill = `${line} L${coords[coords.length - 1][0].toFixed(2)},${h - pad} L${coords[0][0].toFixed(2)},${h - pad} Z`;
  return { line, fill, last: points[points.length - 1], min, max };
}

export function zeroBaselineY(points: number[], h = 120, pad = 4): number | null {
  if (points.length < 2) return null;
  const min = Math.min(...points, 0);
  const max = Math.max(...points, 0);
  const range = max - min || 1;
  return h - pad - ((0 - min) / range) * (h - 2 * pad);
}

export function loadTrades(): Trade[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Trade[]) : [];
  } catch { return []; }
}

export const TRADES_EVENT = "trades:changed";

export function saveTrades(trades: Trade[]): boolean {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(trades));
    window.dispatchEvent(new CustomEvent(TRADES_EVENT));
    return true;
  } catch {
    return false;
  }
}

export function resizeImage(file: File, maxW = 520, quality = 0.72): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, maxW / img.width);
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        canvas.getContext("2d")?.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.onerror = reject;
      img.src = e.target?.result as string;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}