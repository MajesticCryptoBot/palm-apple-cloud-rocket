export type Lane = "USDT" | "USDC";
export type Exchange = "Binance Testnet" | "Binance" | "Bybit" | "Bitget";
export type Tone = "normal" | "trade" | "alert" | "service";

export type CommandSpec = {
  name: string;
  hint: string;
  group: "USDT" | "USDC" | "Isaac" | "Session";
  danger?: boolean;
};

export const COMMANDS: CommandSpec[] = [
  { name: "/pair", hint: "Set the USDT pair", group: "USDT" },
  { name: "/buy_price", hint: "Register a position you already hold", group: "USDT" },
  { name: "/mb", hint: "Manual market buy", group: "USDT" },
  { name: "/status", hint: "Full status panel", group: "USDT" },
  { name: "/balance", hint: "Spot wallet", group: "USDT" },
  { name: "/price", hint: "Live price", group: "USDT" },
  { name: "/compound_status", hint: "Compounding panel", group: "USDT" },
  { name: "/magic_sell", hint: "Emergency sell this pair only", group: "USDT", danger: true },
  { name: "/reset_state", hint: "Clear the USDT lane", group: "USDT", danger: true },
  { name: "/pair2", hint: "Set the USDC pair", group: "USDC" },
  { name: "/buy_price2", hint: "Register a USDC position", group: "USDC" },
  { name: "/mb2", hint: "Manual market buy in USDC", group: "USDC" },
  { name: "/status2", hint: "USDC status panel", group: "USDC" },
  { name: "/balance2", hint: "USDC spot wallet", group: "USDC" },
  { name: "/price2", hint: "USDC pair price", group: "USDC" },
  { name: "/compound_status2", hint: "USDC compounding panel", group: "USDC" },
  { name: "/magic_sell2", hint: "Emergency sell the USDC pair", group: "USDC", danger: true },
  { name: "/reset_state2", hint: "Clear the USDC lane", group: "USDC", danger: true },
  { name: "/isaac_status", hint: "Isaac DCA panel", group: "Isaac" },
  { name: "/emergency_isaac", hint: "Sell Isaac and reset the cycle", group: "Isaac", danger: true },
  { name: "/cancel", hint: "Abort the current question", group: "Session" },
];

export const BASES = [
  "BTC",
  "ETH",
  "SOL",
  "XRP",
  "NEAR",
  "DOGE",
  "BNB",
  "ADA",
  "AVAX",
  "LINK",
  "SUI",
  "LTC",
  "DOT",
  "TON",
  "PEPE",
] as const;

const ANCHORS: Record<string, number> = {
  BTC: 67240,
  ETH: 3284.5,
  SOL: 148.22,
  XRP: 0.5421,
  NEAR: 4.821,
  DOGE: 0.1284,
  BNB: 592.3,
  ADA: 0.3612,
  AVAX: 27.44,
  LINK: 13.82,
  SUI: 2.146,
  LTC: 86.4,
  DOT: 4.22,
  TON: 5.31,
  PEPE: 0.00000912,
};

export type Bal = { free: number; locked: number };

export type Position = {
  entry: number;
  amount: number;
  primary: number;
  secondary: number;
  stopLoss: number;
  trailingStop: number;
  trailingDistance: number;
  rescueCount: number;
  rescueUsed: number;
  scaleCount: number;
  phase: number;
  pattern: string | null;
  rescueDipActive: boolean;
  rescueDipLevel: number | null;
};

export type LaneState = {
  symbol: string | null;
  lastSymbol: string | null;
  allocated: number;
  rescuePool: number;
  position: Position | null;
};

export type IsaacOrder = { entry: number; size: number };

export type IsaacState = {
  symbol: string;
  orders: IsaacOrder[];
  virtualUsdt: number;
  allocated: number;
  initial: number;
  paused: boolean;
  trailingStop: number | null;
  trailingDistance: number | null;
  dipActive: boolean;
  dipLevel: number | null;
  dipDistance: number | null;
  cooldownUntil: number;
};

export type HistEvent = {
  ts: number;
  type: "main_profit" | "isaac_profit";
  amount: number;
  invested?: number;
  profitPct?: number;
  orderInfo?: string;
  lane: Lane | "ISAAC";
};

export type Conv =
  | { kind: "pair"; lane: Lane }
  | { kind: "buy_price"; lane: Lane }
  | { kind: "mb"; lane: Lane };

export type Message = {
  id: string;
  from: "me" | "bot" | "service";
  text: string;
  ts: number;
  pending?: boolean;
  tone?: Tone;
  mono?: boolean;
};

export type InboxJob = { id: string; text: string };

export type Bot = {
  id: string;
  name: string;
  exchange: Exchange;
  online: boolean;
  unread: number;
  lastSeen: number;
  lanes: Record<Lane, LaneState>;
  isaac: IsaacState;
  wallet: Record<string, Bal>;
  history: HistEvent[];
  conversation: Conv | null;
  prices: Record<string, number>;
  anchors: Record<string, number>;
  series: Record<string, number[]>;
  messages: Message[];
  inbox: InboxJob[];
  typing: boolean;
  entryCooldownUntil: number;
  source: "engine" | "bridge";
  bridgePort?: number;
  scriptPath?: string;
  pythonPath?: string;
  commands?: CommandSpec[];
};

export type Reply = { text: string; tone: Tone; mono?: boolean };

const PHASES = ["RUN", "BREATHE", "LOCK", "STEEL", "HARVEST", "MOONSHOT"] as const;
const PHASE_DIST = [0.048, 0.008, 0.006, 0.008, 0.008, 0.015];

export function uid(prefix = "id"): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-4)}`;
}

export function money(n: number, d = 2): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function pxFmt(n: number): string {
  if (!Number.isFinite(n)) return "N/A";
  if (n >= 1000) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1) return n.toFixed(4);
  if (n >= 0.01) return n.toFixed(6);
  return n.toFixed(8);
}

function bal(bot: Bot, ccy: string): Bal {
  return bot.wallet[ccy] ?? { free: 0, locked: 0 };
}

function setBal(bot: Bot, ccy: string, free: number, locked?: number) {
  const prev = bal(bot, ccy);
  bot.wallet[ccy] = { free: Math.max(0, free), locked: locked ?? prev.locked };
}

function addFree(bot: Bot, ccy: string, delta: number) {
  const b = bal(bot, ccy);
  setBal(bot, ccy, b.free + delta, b.locked);
}

export function priceOf(bot: Bot, pair: string): number | null {
  const base = pair.split("/")[0];
  const q = pair.split("/")[1];
  const raw = bot.prices[base];
  if (!raw || raw <= 0) return null;
  return q === "USDC" ? raw * 0.9998 : raw;
}

function ensureBase(bot: Bot, base: string, around?: number) {
  if (!bot.prices[base]) {
    const anchor = around && around > 0 ? around : ANCHORS[base] ?? 1;
    bot.anchors[base] = anchor;
    bot.prices[base] = anchor;
  }
  if (!bot.series[base] || bot.series[base].length < 20) {
    const start = bot.prices[base] * 0.985;
    const arr: number[] = [];
    let p = start;
    for (let i = 0; i < 48; i++) {
      p *= 1 + Math.sin(i / 4) * 0.0018;
      arr.push(p);
    }
    arr.push(bot.prices[base]);
    bot.series[base] = arr;
  }
}

function laneOf(bot: Bot, lane: Lane): LaneState {
  return bot.lanes[lane];
}

function otherLane(lane: Lane): Lane {
  return lane === "USDT" ? "USDC" : "USDT";
}

function example(lane: Lane): string {
  return lane === "USDC" ? "BTC/USDC" : "BTC/USDT";
}

function pairCmd(lane: Lane): string {
  return lane === "USDC" ? "/pair2" : "/pair";
}

function sellCmd(lane: Lane): string {
  return lane === "USDC" ? "/magic_sell2" : "/magic_sell";
}

function parsePair(raw: string, lane: Lane): { ok: true; pair: string } | { ok: false; why: "quote" | "invalid" } {
  let s = raw.trim().toUpperCase().replace(/-/g, "/");
  if (!s.includes("/") && (s.endsWith("USDT") || s.endsWith("USDC"))) {
    const q = s.endsWith("USDC") ? "USDC" : "USDT";
    s = `${s.slice(0, -4)}/${q}`;
  }
  const parts = s.split("/");
  if (parts.length !== 2 || !parts[0]) return { ok: false, why: "invalid" };
  if (parts[1] !== lane) return { ok: false, why: "quote" };
  if (!ANCHORS[parts[0]]) return { ok: false, why: "invalid" };
  return { ok: true, pair: `${parts[0]}/${lane}` };
}

function targetsFor(entry: number, rescue = false, rescuePx?: number) {
  const primary = entry * (rescue ? 1.035 : 1.045);
  const secondary = entry * (rescue ? 1.015 : 1.025);
  const basis = rescue && rescuePx && rescuePx > 0 ? rescuePx : entry;
  const stop = rescue ? basis * 0.9019 : entry * 0.9319;
  const dist = rescue ? basis * 0.0875 : entry * 0.0625;
  let trailingStop = basis - dist;
  const stopLoss = stop > trailingStop ? trailingStop * 0.99 : stop;
  if (trailingStop <= 0) trailingStop = basis * 0.9;
  return { primary, secondary, stopLoss, trailingStop, trailingDistance: dist };
}

function makePosition(entry: number, amount: number, pattern: string | null): Position {
  const t = targetsFor(entry, false);
  return {
    entry,
    amount,
    ...t,
    rescueCount: 0,
    rescueUsed: 0,
    scaleCount: 0,
    phase: 0,
    pattern,
    rescueDipActive: false,
    rescueDipLevel: null,
  };
}

function ema(values: number[], period: number): number {
  if (!values.length) return 0;
  const k = 2 / (period + 1);
  let e = values[0];
  for (const v of values) e = v * k + e * (1 - k);
  return e;
}

function rsi(values: number[]): number {
  if (values.length < 15) return 50;
  let g = 0;
  let l = 0;
  const slice = values.slice(-15);
  for (let i = 1; i < slice.length; i++) {
    const d = slice[i] - slice[i - 1];
    if (d >= 0) g += d;
    else l -= d;
  }
  if (l === 0) return 100;
  const rs = g / l;
  return 100 - 100 / (1 + rs);
}

function indicators(bot: Bot, pair: string, price: number) {
  const base = pair.split("/")[0];
  ensureBase(bot, base, price);
  const closes = bot.series[base];
  const e5 = ema(closes, 5);
  const e9 = ema(closes, 9);
  const e13 = ema(closes, 13);
  const e21 = ema(closes, 21);
  const e50 = ema(closes, 50);
  const r = rsi(closes);
  const atr = Math.max(price * 0.008, Math.abs(closes[closes.length - 1] - closes[Math.max(0, closes.length - 14)]) / 6);
  const macd = e9 - e21;
  const signal = macd * 0.82;
  const hist = macd - signal;
  const vwap = closes.slice(-20).reduce((a, b) => a + b, 0) / Math.min(20, closes.length);
  const support = Math.min(...closes.slice(-20));
  const high = Math.max(...closes.slice(-20));
  const fib = support + 0.618 * (high - support);
  let score = 0;
  if (e5 > e9 && e9 > e13 && e13 > e21 && e21 > e50 * 0.995) score += 40;
  else if (e9 > e21) score += 24;
  if (r > 48 && r < 72) score += 18;
  if (price > Math.max(e5, e9, e21)) score += 12;
  if (hist > 0) score += 10;
  if (r > 74) score -= 18;
  if (price > e21 * 1.03) score -= 10;
  score = Math.max(0, Math.min(99, Math.round(score)));
  return { e5, e9, e13, e21, e50, r, atr, macd, signal, hist, vwap, support, fib, score };
}

function fmtTg(title: string, rows: string[]): string {
  return [`━━ ${title} ━━`, ...rows].join("\n");
}

function phaseIndex(pct: number): number {
  if (pct >= 10.5) return 5;
  if (pct >= 7.8) return 4;
  if (pct >= 5.8) return 3;
  if (pct >= 4.2) return 2;
  if (pct >= 1.8) return 1;
  return 0;
}

function trackedAmount(bot: Bot, pair: string): number {
  const lane: Lane = pair.endsWith("USDC") ? "USDC" : "USDT";
  const st = laneOf(bot, lane);
  if (st.symbol === pair && st.position) return st.position.amount;
  return 0;
}

function sellableBase(bot: Bot, pair: string): number {
  const base = pair.split("/")[0];
  const free = bal(bot, base).free;
  const lane: Lane = pair.endsWith("USDC") ? "USDC" : "USDT";
  const other = laneOf(bot, otherLane(lane));
  const otherBase = other.symbol?.split("/")[0];
  const otherAmt = other.position && otherBase === base ? other.position.amount : 0;
  if (otherAmt > 0) {
    const tracked = trackedAmount(bot, pair);
    return Math.min(free, tracked > 0 ? tracked : Math.max(0, free - otherAmt));
  }
  return free;
}

function recordMain(bot: Bot, lane: Lane, profit: number, invested: number, now: number) {
  const pct = invested > 0 ? (profit / invested) * 100 : 0;
  bot.history.push({
    ts: now,
    type: "main_profit",
    amount: profit,
    invested,
    profitPct: pct,
    lane,
  });
  if (bot.history.length > 400) bot.history.splice(0, bot.history.length - 400);
  const st = laneOf(bot, lane);
  st.allocated = Math.max(100, st.allocated + profit);
}

function statusText(bot: Bot, lane: Lane): string {
  const st = laneOf(bot, lane);
  const pair = st.lastSymbol || st.symbol;
  if (!pair) return `No trading pairs set. Use ${pairCmd(lane)} to set a pair.`;
  const price = priceOf(bot, pair);
  if (!price) return `Error fetching status for ${pair}: No price`;
  const base = pair.split("/")[0];
  const quote = lane;
  const b = bal(bot, base);
  const q = bal(bot, quote);
  const ind = indicators(bot, pair, price);
  const btc = priceOf(bot, "BTC/USDT");
  const pos = st.symbol === pair ? st.position : null;
  let profit = "Profit: N/A";
  if (pos) {
    const pct = ((price - pos.entry) / pos.entry) * 100;
    const usd = (price - pos.entry) * pos.amount;
    profit = `Profit: ${pct.toFixed(2)}% ($${usd.toFixed(2)})`;
  }
  const emaBias = ind.e9 > ind.e21 ? "Bullish" : ind.e9 < ind.e21 ? "Bearish" : "Neutral";
  const shortBias = ind.e5 > ind.e13 ? "BullishShort" : "BearishShort";
  const ema50 = price > ind.e50 ? "Bullish" : "Bearish";
  const indicatorsBlock = [
    `EMA9 ${pxFmt(ind.e9)} / EMA21 ${pxFmt(ind.e21)}  ${emaBias}`,
    `EMA5 ${pxFmt(ind.e5)} / EMA13 ${pxFmt(ind.e13)}  ${shortBias}`,
    `EMA50 ${pxFmt(ind.e50)}  ${ema50}`,
    `RSI ${ind.r.toFixed(2)}`,
    `ATR ${pxFmt(ind.atr)} (${((ind.atr / price) * 100).toFixed(2)}%)`,
    `MACD ${ind.macd.toFixed(4)} / Signal ${ind.signal.toFixed(4)} / Hist ${ind.hist.toFixed(4)}`,
    `VWAP ${pxFmt(ind.vwap)}`,
    `Support ${pxFmt(ind.support)}`,
    `Fib 61.8% ${pxFmt(ind.fib)}`,
  ].join("\n");
  let orders = "None";
  if (pos) {
    const distPct = (pos.trailingDistance / price) * 100;
    const lines = [
      "Side: BUY",
      `Amount: ${pos.amount.toFixed(6)} ${base}`,
      `Entry: ${pxFmt(pos.entry)}`,
      `Primary: ${pxFmt(pos.primary)}`,
      `Secondary: ${pxFmt(pos.secondary)}`,
      `Stop-loss: ${pxFmt(pos.stopLoss)}`,
      `Trailing stop: ${pxFmt(pos.trailingStop)}`,
      `Trail distance: ${distPct.toFixed(2)}%`,
      `Phase: ${PHASES[pos.phase] ?? "RUN"}`,
      `Rescue: ${pos.rescueCount}/5`,
      `Scale: ${pos.scaleCount}/3`,
      `Pattern: ${pos.pattern ?? "n/a"}`,
    ];
    if (pos.rescueDipActive && pos.rescueDipLevel) {
      lines.push(`Rescue trailing dip: ACTIVE @ ${pxFmt(pos.rescueDipLevel)}`);
    }
    orders = lines.join("\n");
  }
  const radar =
    ind.score >= 65
      ? `Valid Patterns (>=65%): 1 found\n\nPATTERN 6: EMA Momentum Alignment (Elite)\nMatch: ${ind.score}%`
      : "No Qualified Pattern to trigger For Now";
  return [
    "Status Panel:",
    "",
    `Pair: ${pair}`,
    `Live Price: $${pxFmt(price)}`,
    `Live BTC Price: ${btc ? "$" + pxFmt(btc) : "N/A"}`,
    "",
    "Balances (Wallet):",
    `Free: ${b.free.toFixed(6)} ${base}`,
    `Locked: ${b.locked.toFixed(6)} ${base}`,
    `Free ${quote}: ${q.free.toFixed(2)} ${quote}`,
    `Locked ${quote}: ${q.locked.toFixed(2)} ${quote}`,
    "",
    "Live Indicators:",
    indicatorsBlock,
    "",
    profit,
    "",
    "Orders:",
    orders,
    "",
    radar,
    "",
    `Actual Price: $${pxFmt(price)}`,
    `BTC Price: ${btc ? "$" + pxFmt(btc) : "N/A"}`,
  ].join("\n");
}

function balanceText(bot: Bot, lane: Lane): string {
  const st = laneOf(bot, lane);
  const shown = st.lastSymbol || st.symbol;
  if (!shown) return `No pair set. Use ${pairCmd(lane)}`;
  const base = shown.split("/")[0];
  const b = bal(bot, base);
  const q = bal(bot, lane);
  return `Spot Wallet: ${b.free.toFixed(8)} ${base} (free), ${b.locked.toFixed(8)} ${base} (locked), ${q.free.toFixed(2)} ${lane} (free), ${q.locked.toFixed(2)} ${lane} (locked)`;
}

function priceText(bot: Bot, lane: Lane): string {
  const st = laneOf(bot, lane);
  const shown = st.lastSymbol || st.symbol;
  if (!shown) return `No pair set. Use ${pairCmd(lane)}`;
  const price = priceOf(bot, shown);
  if (!price) return `Error fetching price for ${shown}`;
  return `${shown}: $${pxFmt(price)}`;
}

function compoundText(bot: Bot, lane: Lane | "ALL"): string {
  if (lane === "USDC") {
    const profits = bot.history.filter((e) => e.type === "main_profit" && e.lane === "USDC");
    const total = profits.reduce((s, e) => s + e.amount, 0);
    const alloc = laneOf(bot, "USDC").allocated;
    const q = bal(bot, "USDC");
    const lines = [
      "COMPOUNDING STATUS PANEL (USDC)",
      "",
      `Total Wallet USDC     : $${money(q.free)}`,
      "",
      `1. USDC Lane Asset    : $${money(alloc)}   (+$${money(total)} growth)`,
      "   (Started at 5000)",
      "   This lane does not include Isaac DCA.",
      "",
      `2. Profit from USDC lane: $${money(total)}`,
      `3. USDC lane trades     : ${profits.length} trades`,
      "",
      laneOf(bot, "USDC").symbol ? `Pair: ${laneOf(bot, "USDC").symbol}` : "Pair: not set. Use /pair2",
      "",
    ];
    const pos = laneOf(bot, "USDC").position;
    const sym = laneOf(bot, "USDC").symbol;
    if (pos && sym) lines.push(`Open: ${sym} | Invested $${money(pos.entry * pos.amount)}`, "");
    lines.push("4. Last 30 USDC Lane Trades:");
    if (!profits.length) lines.push("   (none yet)");
    else {
      for (const t of profits.slice(-30).reverse()) {
        const time = new Date(t.ts).toISOString().slice(0, 16).replace("T", " ");
        if (t.invested != null && t.profitPct != null) {
          lines.push(`   ${time} | $${money(t.invested)} -> TP: +$${t.amount.toFixed(2)} / ${t.profitPct.toFixed(2)}%`);
        } else lines.push(`   ${time} | Profit: +$${t.amount.toFixed(2)}`);
      }
    }
    return lines.join("\n");
  }
  const main = bot.history.filter((e) => e.type === "main_profit" && e.lane === "USDT");
  const isaac = bot.history.filter((e) => e.type === "isaac_profit");
  const mainSum = main.reduce((s, e) => s + e.amount, 0);
  const isaacSum = isaac.reduce((s, e) => s + e.amount, 0);
  const growth = mainSum + isaacSum;
  const q = bal(bot, "USDT");
  const lines = [
    "COMPOUNDING STATUS PANEL",
    "",
    `Total Wallet USDT     : $${money(q.free)}`,
    "",
    `1. Main Bot Asset     : $${money(laneOf(bot, "USDT").allocated)}   (+$${money(growth)} Total Growth)`,
    "   (Started at 5000)",
    `   ISAAC DCA Contribution : +$${money(isaacSum)}`,
    `   Main Bot Contribution  : +$${money(mainSum)}`,
    "",
    `2. ISAAC DCA Asset    : $${money(bot.isaac.allocated)}`,
    `   Initial Buy Size   : $${bot.isaac.initial.toFixed(0)}`,
    "",
    `3. Profit from Main Bot : $${money(mainSum)} (${((mainSum / 5000) * 100).toFixed(1)}% from initial)`,
    `4. Profit from ISAAC DCA: $${money(isaacSum)}`,
    `5. Combined Profit      : $${money(mainSum + isaacSum)}`,
    "",
    `6. Main Bot Trades    : ${main.length} trades`,
    `7. ISAAC DCA Trades   : ${isaac.length} trades`,
    "",
  ];
  const pos = laneOf(bot, "USDT").position;
  const sym = laneOf(bot, "USDT").symbol;
  if (pos && sym) {
    lines.push("Open Main Bot Positions:", `   OPEN ${sym} | Invested: $${money(pos.entry * pos.amount)}`, "");
  }
  if (bot.isaac.orders.length) {
    const cost = bot.isaac.orders.reduce((s, o) => s + o.size * o.entry, 0);
    lines.push(
      "Open ISAAC DCA Positions:",
      `   OPEN | Invested: $${money(cost)} (${bot.isaac.orders.length} orders)`,
      "",
    );
  }
  lines.push("8. Last 30 Main Bot Trades:");
  if (!main.length) lines.push("   (none yet)");
  else {
    for (const t of main.slice(-30).reverse()) {
      const time = new Date(t.ts).toISOString().slice(0, 16).replace("T", " ");
      if (t.invested != null && t.profitPct != null) {
        lines.push(`   ${time} | $${money(t.invested)} -> TP: +$${t.amount.toFixed(2)} / ${t.profitPct.toFixed(2)}%`);
      } else lines.push(`   ${time} | Profit: +$${t.amount.toFixed(2)}`);
    }
  }
  lines.push("", "9. Last 30 ISAAC DCA Trades:");
  if (!isaac.length) lines.push("   (none yet)");
  else {
    for (const t of isaac.slice(-30).reverse()) {
      const time = new Date(t.ts).toISOString().slice(0, 16).replace("T", " ");
      const info = t.orderInfo ? ` (${t.orderInfo})` : "";
      if (t.invested != null && t.profitPct != null) {
        lines.push(`   ${time} | $${money(t.invested)}${info} -> TP: +$${t.amount.toFixed(2)} / ${t.profitPct.toFixed(2)}%`);
      } else lines.push(`   ${time} | Profit: +$${t.amount.toFixed(2)}`);
    }
  }
  return lines.join("\n");
}

function isaacDynamicTp(n: number): number {
  if (n <= 1) return 2.5;
  if (n === 2) return 2.8;
  if (n === 3) return 3.2;
  if (n === 4) return 3.7;
  if (n === 5) return 4.2;
  if (n === 6) return 4.7;
  return 5.2;
}

function isaacNextDrop(n: number): number {
  if (n <= 0) return 0;
  if (n === 1) return 3;
  if (n === 2) return 5;
  if (n === 3) return 8;
  if (n === 4) return 24;
  if (n === 5) return 32;
  return 40;
}

function isaacStatusText(bot: Bot): string {
  const isaac = bot.isaac;
  const price = priceOf(bot, isaac.symbol);
  if (!price) return "ISAAC STATUS ERROR: Unable to fetch price.";
  const base = isaac.symbol.split("/")[0];
  const orders = isaac.orders;
  const n = orders.length;
  const total = orders.reduce((s, o) => s + o.size, 0);
  const avg = total > 0 ? orders.reduce((s, o) => s + o.size * o.entry, 0) / total : 0;
  const last = n ? orders[n - 1].entry : 0;
  const drop = isaacNextDrop(n);
  const nextBuy = last > 0 ? `${pxFmt(last * (1 - drop / 100))} (-${drop}% from last entry)` : "Waiting for first entry";
  const tpPct = isaacDynamicTp(n);
  const tp = avg > 0 ? avg * (1 + tpPct / 100) : 0;
  const pnl = avg > 0 ? (price - avg) * total : 0;
  const pnlPct = avg > 0 ? ((price - avg) / avg) * 100 : 0;
  const b = bal(bot, base);
  const q = bal(bot, "USDT");
  const used = b.free * price;
  const available = Math.max(0, isaac.allocated - used);
  const virtual = Math.min(available, isaac.virtualUsdt);
  const dcaValue = b.free * price;
  const port = q.free + dcaValue;
  const weight = port > 0 ? (dcaValue / port) * 100 : 0;
  const lines = [
    "ISAAC DCA STATUS PANEL",
    "",
    `Symbol: ${isaac.symbol}`,
    `Status: ${isaac.paused ? "Paused" : "Running"}`,
    "",
    `Live Price: $${pxFmt(price)}`,
    `Purchased Amount: ${total.toFixed(6)} ${base}`,
    `Average Entry: $${pxFmt(avg)}`,
    `Last Entry: $${pxFmt(last)}`,
    "",
    "Wallet:",
    `  ${b.free.toFixed(6)} ${base}`,
    `  ${q.free.toFixed(2)} USDT (total)`,
    "",
    `Virtual USDT Pool: $${virtual.toFixed(2)} / ${isaac.allocated.toFixed(0)}`,
    `Initial Buy Size: $${isaac.initial.toFixed(0)} (Scaled)`,
    `Orders in Cycle: ${n}/7`,
    "",
    `Take Profit: $${pxFmt(tp)} (+${tpPct}% Dynamic)`,
    `Next Buy Trigger: ${nextBuy}`,
    "",
    "Unrealized PnL:",
    `  ${pnl.toFixed(2)} USDT`,
    `  ${pnlPct.toFixed(2)}%`,
    "",
    `Portfolio Weight: $${dcaValue.toFixed(2)} / $${port.toFixed(2)} (${weight.toFixed(2)}%)`,
    "",
    `Trailing Dip: ${isaac.dipActive ? "ACTIVE" : "Inactive"}`,
  ];
  if (isaac.dipActive && isaac.dipLevel) {
    lines.push(`  Dip Level: $${pxFmt(isaac.dipLevel)}`);
  }
  lines.push("", `Trailing Stop: ${isaac.trailingStop != null ? "ACTIVE" : "Inactive"}`);
  if (isaac.trailingStop != null) lines.push(`  Stop Level: $${pxFmt(isaac.trailingStop)}`);
  lines.push(
    "",
    "Dynamic Drop Settings:",
    "  Order 1  Direct Buy  5000 USDT",
    "  Order 2  -3%   1500 USDT",
    "  Order 3  -5%   2250 USDT",
    "  Order 4  -8%   3375 USDT",
    "  Order 5  -24%  5062.50 USDT",
    "  Order 6  -32%  7593.75 USDT",
    "  Order 7  Trailing Dip @ -40%  11390.63 USDT",
    "",
    "Dynamic TP Settings:",
    "  Order 1  +2.5%",
    "  Order 2  +2.8%",
    "  Order 3  +3.2%",
    "  Order 4  +3.7%",
    "  Order 5  +4.2%",
    "  Order 6  +4.7%",
    "  Order 7  +5.2%",
  );
  return lines.join("\n");
}

function setPair(bot: Bot, lane: Lane, raw: string, replies: Reply[]) {
  const parsed = parsePair(raw, lane);
  if (!parsed.ok) {
    if (parsed.why === "quote") {
      replies.push({
        tone: "normal",
        text:
          lane === "USDC"
            ? `/pair2 only accepts a USDC pair (e.g. ${example(lane)}). USDT pairs use /pair.`
            : `/pair only accepts a USDT pair (e.g. ${example(lane)}). USDC pairs use /pair2.`,
      });
    } else {
      replies.push({ tone: "normal", text: `Invalid pair: ${raw.toUpperCase()}. Try ${example(lane)}.` });
    }
    return;
  }
  const st = laneOf(bot, lane);
  if (st.position && st.symbol && st.symbol !== parsed.pair) {
    replies.push({
      tone: "alert",
      text: `${st.symbol} is still open on this lane. Close it with ${sellCmd(lane)} before switching pairs.`,
    });
    return;
  }
  st.symbol = parsed.pair;
  st.lastSymbol = parsed.pair;
  ensureBase(bot, parsed.pair.split("/")[0]);
  bot.conversation = null;
  replies.push({ tone: "normal", text: `${parsed.pair} pair added` });
}

function promptPair(bot: Bot, lane: Lane, replies: Reply[]) {
  bot.conversation = { kind: "pair", lane };
  replies.push({ tone: "normal", text: `Enter trading pair (e.g., ${example(lane)})` });
}

function promptBuy(bot: Bot, lane: Lane, replies: Reply[]) {
  const ex = lane === "USDC" ? "SOL/USDC 150 2" : "BTC/USDT 80000 0.1";
  bot.conversation = { kind: "buy_price", lane };
  replies.push({
    tone: "normal",
    text: `Enter pair, buy price, and amount: <pair> <buy_price> <amount> (e.g., ${ex}). This command only affects ${pairCmd(lane)}.`,
  });
}

function applyBuyPrice(bot: Bot, lane: Lane, args: string[], replies: Reply[], keepConversation: boolean) {
  const ex = lane === "USDC" ? "SOL/USDC 150 2" : "BTC/USDT 80000 0.1";
  const st = laneOf(bot, lane);
  if (!st.symbol) {
    replies.push({
      tone: "normal",
      text: lane === "USDC" ? "Set a trading pair with /pair2 first" : "Set a trading pair with /pair first",
    });
    if (!keepConversation) bot.conversation = null;
    return;
  }
  if (args.length !== 3) {
    replies.push({ tone: "normal", text: `Use: <pair> <buy_price> <amount> (e.g., ${ex})` });
    if (keepConversation) bot.conversation = { kind: "buy_price", lane };
    return;
  }
  const parsed = parsePair(args[0], lane);
  if (!parsed.ok) {
    replies.push({
      tone: "normal",
      text:
        parsed.why === "quote"
          ? lane === "USDC"
            ? `/buy_price2 only accepts a USDC pair, got ${args[0].toUpperCase()}.`
            : `/buy_price only accepts a USDT pair, got ${args[0].toUpperCase()}.`
          : `Invalid pair: ${args[0].toUpperCase()}`,
    });
    if (keepConversation) bot.conversation = { kind: "buy_price", lane };
    return;
  }
  if (parsed.pair !== st.symbol) {
    replies.push({
      tone: "normal",
      text: `${parsed.pair} is not the active pair. Current pair is ${st.symbol}.`,
    });
    if (keepConversation) bot.conversation = { kind: "buy_price", lane };
    return;
  }
  const buy = Number(args[1]);
  const amount = Number(args[2]);
  if (!Number.isFinite(buy) || !Number.isFinite(amount)) {
    replies.push({ tone: "normal", text: "Buy price and amount must be numbers" });
    if (keepConversation) bot.conversation = { kind: "buy_price", lane };
    return;
  }
  if (buy <= 0 || amount <= 0) {
    replies.push({ tone: "normal", text: "Buy price and amount must be positive" });
    if (keepConversation) bot.conversation = { kind: "buy_price", lane };
    return;
  }
  const base = parsed.pair.split("/")[0];
  const held = bal(bot, base).free;
  if (amount > held + 1e-8) {
    replies.push({
      tone: "normal",
      text: `Insufficient ${base} balance: ${held.toFixed(8)} < ${amount.toFixed(8)}`,
    });
    if (keepConversation) bot.conversation = { kind: "buy_price", lane };
    return;
  }
  const pos = makePosition(buy, amount, "Manual registration");
  const live = priceOf(bot, parsed.pair) ?? buy;
  pos.trailingDistance = Math.max(pos.trailingDistance, live * 0.048);
  pos.trailingStop = live - pos.trailingDistance;
  st.position = pos;
  bot.conversation = null;
  replies.push({
    tone: "trade",
    mono: true,
    text: `Position initialized for ${parsed.pair}: ${amount.toFixed(8)} ${base} at entry price $${pxFmt(buy)}\nPrimary $${pxFmt(pos.primary)}, Secondary $${pxFmt(pos.secondary)}, Stop-Loss $${pxFmt(pos.stopLoss)}, Trailing Stop $${pxFmt(pos.trailingStop)}`,
  });
}

function promptMb(bot: Bot, lane: Lane, replies: Reply[]) {
  const st = laneOf(bot, lane);
  if (!st.symbol) {
    replies.push({ tone: "normal", text: `No trading pair set. Use ${pairCmd(lane)} first.` });
    bot.conversation = null;
    return;
  }
  bot.conversation = { kind: "mb", lane };
  replies.push({
    tone: "normal",
    text: `Manual buy on ${st.symbol}\nSend the ${lane} amount (e.g. 1500)\n/cancel to abort`,
  });
}

function applyMb(bot: Bot, lane: Lane, raw: string, replies: Reply[]) {
  const st = laneOf(bot, lane);
  let requested = Number(String(raw).replace(/,/g, "").trim());
  if (!Number.isFinite(requested)) {
    replies.push({ tone: "normal", text: "Invalid amount. Send a number (e.g. 1500)." });
    bot.conversation = { kind: "mb", lane };
    return;
  }
  if (requested <= 0) {
    replies.push({ tone: "normal", text: "Amount must be > 0." });
    bot.conversation = { kind: "mb", lane };
    return;
  }
  if (!st.symbol) {
    replies.push({ tone: "normal", text: `No trading pair set. Use ${pairCmd(lane)} first.` });
    bot.conversation = null;
    return;
  }
  const price = priceOf(bot, st.symbol);
  if (!price) {
    replies.push({ tone: "normal", text: `Cannot get current price for ${st.symbol}.` });
    bot.conversation = null;
    return;
  }
  const wallet = bal(bot, lane).free;
  const use = Math.floor(Math.min(requested, wallet) * 100) / 100;
  if (use < 10) {
    replies.push({
      tone: "alert",
      text: `Insufficient ${lane}: requested $${requested.toFixed(2)} | wallet $${wallet.toFixed(2)} | using $${use.toFixed(2)}`,
    });
    bot.conversation = null;
    return;
  }
  const base = st.symbol.split("/")[0];
  const qty = use / price;
  addFree(bot, lane, -use);
  addFree(bot, base, qty);
  const orderId = String(800000000 + Math.floor(Math.random() * 100000000));
  bot.conversation = null;
  replies.push({
    tone: "trade",
    mono: true,
    text: `MANUAL MARKET BUY EXECUTED\n${base}: ${qty.toFixed(6)} @ ~${pxFmt(price)}\nRequested: $${requested.toFixed(2)} ${lane} | Used: $${use.toFixed(2)} | Wallet: $${bal(bot, lane).free.toFixed(2)}\nOrder ID: ${orderId}\n(No pattern targets or trailing stop set — manual buy)`,
  });
}

function magicSell(bot: Bot, lane: Lane, replies: Reply[], now: number) {
  const st = laneOf(bot, lane);
  const pair = st.symbol;
  if (!pair) {
    replies.push({ tone: "normal", text: `No trading pair set (${pairCmd(lane)}). Nothing to sell.` });
    return;
  }
  const base = pair.split("/")[0];
  const qty = sellableBase(bot, pair);
  if (qty <= 1e-8) {
    replies.push({ tone: "normal", text: `No ${base} available to sell.` });
    return;
  }
  const price = priceOf(bot, pair);
  if (!price) {
    replies.push({ tone: "normal", text: `Cannot get price for ${pair}.` });
    return;
  }
  const pos = st.position;
  const invested = pos ? pos.entry * pos.amount : qty * price;
  const soldQty = pos ? Math.min(qty, pos.amount || qty) : qty;
  const value = soldQty * price;
  const profit = pos ? (price - pos.entry) * soldQty : 0;
  addFree(bot, base, -soldQty);
  addFree(bot, lane, value);
  if (pos) {
    recordMain(bot, lane, profit, invested, now);
    st.position = null;
  }
  const orderId = String(700000000 + Math.floor(Math.random() * 100000000));
  replies.push({
    tone: "trade",
    mono: true,
    text: `MAGIC SELL (EMERGENCY) EXECUTED\n${base}: ${soldQty.toFixed(6)} sold @ ~${pxFmt(price)}\nRecovered ≈ $${value.toFixed(2)} ${lane}\nOrder ID: ${orderId}\nISAAC DCA was NOT affected.`,
  });
}

function resetLane(bot: Bot, lane: Lane, replies: Reply[]) {
  const st = laneOf(bot, lane);
  st.symbol = null;
  st.lastSymbol = null;
  st.position = null;
  replies.push({
    tone: "alert",
    text: lane === "USDC" ? "USDC lane reset. Set a new pair with /pair2." : "Bot state reset. Set new pair with /pair.",
  });
}

function emergencyIsaac(bot: Bot, replies: Reply[], now: number) {
  const base = bot.isaac.symbol.split("/")[0];
  const tracked = bot.isaac.orders.reduce((s, o) => s + o.size, 0);
  const qty = Math.min(bal(bot, base).free, tracked > 0 ? tracked : bal(bot, base).free);
  if (qty <= 1e-8) {
    replies.push({ tone: "normal", text: `No ${base} balance available for ISAAC DCA to sell.` });
    return;
  }
  const price = priceOf(bot, bot.isaac.symbol) ?? 0;
  const cost = bot.isaac.orders.reduce((s, o) => s + o.size * o.entry, 0);
  const profit = qty * price - cost;
  addFree(bot, base, -qty);
  addFree(bot, "USDT", qty * price);
  if (bot.isaac.orders.length) {
    bot.history.push({
      ts: now,
      type: "isaac_profit",
      amount: profit,
      invested: cost,
      profitPct: cost > 0 ? (profit / cost) * 100 : 0,
      orderInfo: `Orders: ${bot.isaac.orders.length}`,
      lane: "ISAAC",
    });
    laneOf(bot, "USDT").allocated = Math.max(100, laneOf(bot, "USDT").allocated + profit);
  }
  bot.isaac.orders = [];
  bot.isaac.trailingStop = null;
  bot.isaac.trailingDistance = null;
  bot.isaac.dipActive = false;
  bot.isaac.dipLevel = null;
  bot.isaac.virtualUsdt = bot.isaac.allocated;
  replies.push({
    tone: "trade",
    mono: true,
    text: `EMERGENCY SELL SUCCESSFUL\nSold ${qty.toFixed(6)} ${base} @ ${pxFmt(price)}\nCycle reset to 0/7. New buy cycle will start soon.`,
  });
}

function dispatchCommand(bot: Bot, text: string, replies: Reply[], now: number) {
  const parts = text.trim().split(/\s+/);
  let cmd = parts[0].toLowerCase();
  const args = parts.slice(1);
  if (cmd.startsWith("/buy_price2")) cmd = "/buy_price2";
  bot.conversation = null;
  switch (cmd) {
    case "/pair":
      if (args.length) setPair(bot, "USDT", args[0], replies);
      else promptPair(bot, "USDT", replies);
      return;
    case "/pair2":
      if (args.length) setPair(bot, "USDC", args[0], replies);
      else promptPair(bot, "USDC", replies);
      return;
    case "/buy_price":
      if (args.length >= 3) applyBuyPrice(bot, "USDT", args.slice(0, 3), replies, false);
      else promptBuy(bot, "USDT", replies);
      return;
    case "/buy_price2":
      if (args.length >= 3) applyBuyPrice(bot, "USDC", args.slice(0, 3), replies, false);
      else promptBuy(bot, "USDC", replies);
      return;
    case "/mb":
      if (args.length) applyMb(bot, "USDT", args[0], replies);
      else promptMb(bot, "USDT", replies);
      return;
    case "/mb2":
      if (args.length) applyMb(bot, "USDC", args[0], replies);
      else promptMb(bot, "USDC", replies);
      return;
    case "/status":
      replies.push({ tone: "normal", mono: true, text: statusText(bot, "USDT") });
      return;
    case "/status2":
      replies.push({ tone: "normal", mono: true, text: statusText(bot, "USDC") });
      return;
    case "/balance":
      replies.push({ tone: "normal", mono: true, text: balanceText(bot, "USDT") });
      return;
    case "/balance2":
      replies.push({ tone: "normal", mono: true, text: balanceText(bot, "USDC") });
      return;
    case "/price":
      replies.push({ tone: "normal", text: priceText(bot, "USDT") });
      return;
    case "/price2":
      replies.push({ tone: "normal", text: priceText(bot, "USDC") });
      return;
    case "/compound_status":
      replies.push({ tone: "normal", mono: true, text: compoundText(bot, "ALL") });
      return;
    case "/compound_status2":
      replies.push({ tone: "normal", mono: true, text: compoundText(bot, "USDC") });
      return;
    case "/isaac_status":
      replies.push({ tone: "normal", mono: true, text: isaacStatusText(bot) });
      return;
    case "/magic_sell":
      magicSell(bot, "USDT", replies, now);
      return;
    case "/magic_sell2":
      magicSell(bot, "USDC", replies, now);
      return;
    case "/reset_state":
      resetLane(bot, "USDT", replies);
      return;
    case "/reset_state2":
      resetLane(bot, "USDC", replies);
      return;
    case "/emergency_isaac":
      emergencyIsaac(bot, replies, now);
      return;
    case "/cancel":
      replies.push({ tone: "service", text: "Nothing to cancel." });
      return;
    default:
      replies.push({
        tone: "normal",
        text: "Unknown command. Type / to open this bot's command list.",
      });
  }
}

function answerConversation(bot: Bot, text: string, replies: Reply[]) {
  const conv = bot.conversation;
  if (!conv) return;
  if (conv.kind === "pair") {
    setPair(bot, conv.lane, text, replies);
    return;
  }
  if (conv.kind === "buy_price") {
    applyBuyPrice(bot, conv.lane, text.trim().split(/\s+/), replies, true);
    return;
  }
  applyMb(bot, conv.lane, text, replies);
}

export function applyUserText(bot: Bot, text: string, now: number): { bot: Bot; replies: Reply[] } {
  const next: Bot = structuredClone(bot);
  const replies: Reply[] = [];
  const trimmed = text.trim();
  if (!trimmed) return { bot: next, replies };
  if (trimmed.startsWith("/")) {
    const conv = next.conversation;
    if (trimmed.split(/\s+/)[0].toLowerCase() === "/cancel" && conv) {
      next.conversation = null;
      replies.push({
        tone: "service",
        text: conv.kind === "pair" ? "Pair setting cancelled" : "Cancelled.",
      });
      return { bot: next, replies };
    }
    dispatchCommand(next, trimmed, replies, now);
    return { bot: next, replies };
  }
  if (next.conversation) {
    answerConversation(next, trimmed, replies);
    return { bot: next, replies };
  }
  replies.push({
    tone: "normal",
    text: "Send a command. Type / to see the list, the same way you would in Telegram.",
  });
  return { bot: next, replies };
}

function closePosition(bot: Bot, lane: Lane, price: number, reason: string, now: number, replies: Reply[]) {
  const st = laneOf(bot, lane);
  const pos = st.position;
  const pair = st.symbol;
  if (!pos || !pair) return;
  const base = pair.split("/")[0];
  const qty = Math.min(pos.amount, bal(bot, base).free || pos.amount);
  const value = qty * price;
  const profit = (price - pos.entry) * qty;
  const invested = pos.entry * qty;
  addFree(bot, base, -qty);
  addFree(bot, lane, value);
  recordMain(bot, lane, profit, invested, now);
  st.position = null;
  bot.entryCooldownUntil = now + 45_000;
  replies.push({
    tone: profit >= 0 ? "trade" : "alert",
    mono: true,
    text: `${reason}\n${pair}\nSold ${qty.toFixed(6)} ${base} @ ${pxFmt(price)}\nPnL ${profit >= 0 ? "+" : ""}$${profit.toFixed(2)} (${invested > 0 ? ((profit / invested) * 100).toFixed(2) : "0.00"}%)\nPosition closed. Watching for the next pattern.`,
  });
}

function openManaged(bot: Bot, lane: Lane, price: number, pattern: string, now: number, replies: Reply[]) {
  const st = laneOf(bot, lane);
  if (!st.symbol || st.position) return;
  if (now < bot.entryCooldownUntil) return;
  const quoteFree = bal(bot, lane).free;
  const budget = Math.min(st.allocated * 0.35, quoteFree * 0.45);
  const spend = Math.floor(budget * 100) / 100;
  if (spend < 50) return;
  const base = st.symbol.split("/")[0];
  const qty = spend / price;
  addFree(bot, lane, -spend);
  addFree(bot, base, qty);
  const pos = makePosition(price, qty, pattern);
  pos.trailingDistance = price * 0.048;
  pos.trailingStop = price - pos.trailingDistance;
  st.position = pos;
  bot.entryCooldownUntil = now + 20_000;
  replies.push({
    tone: "trade",
    mono: true,
    text: `PATTERN 6: EMA Momentum Alignment (Elite)\nMatch: 91%\n\nBuy Order Filled and Targets Set\n${base}: ${qty.toFixed(6)} at ${pxFmt(price)}\nPrimary: ${pxFmt(pos.primary)}\nSecondary: ${pxFmt(pos.secondary)}\nStop-Loss: ${pxFmt(pos.stopLoss)}\nTrailing Stop: ${pxFmt(pos.trailingStop)}`,
  });
}

function managePosition(bot: Bot, lane: Lane, now: number, replies: Reply[]) {
  const st = laneOf(bot, lane);
  const pos = st.position;
  const pair = st.symbol;
  if (!pos || !pair) return;
  const price = priceOf(bot, pair);
  if (!price) return;
  const pct = ((price - pos.entry) / pos.entry) * 100;
  const nextPhase = phaseIndex(pct);
  if (pos.phase === 0) {
    const runDist = price * 0.048;
    if (pos.trailingDistance < price * 0.012 || Math.abs(pos.trailingDistance - runDist) / price > 0.02) {
      pos.trailingDistance = runDist;
    }
  }
  const candidate = price - pos.trailingDistance;
  if (candidate > pos.trailingStop) pos.trailingStop = candidate;

  if (nextPhase > pos.phase) {
    pos.phase = nextPhase;
    const dist = price * PHASE_DIST[nextPhase];
    const candidateStop = price - dist;
    pos.trailingDistance = dist;
    if (candidateStop > pos.trailingStop) pos.trailingStop = candidateStop;
    const locked = (pos.trailingStop / pos.entry - 1) * 100;
    const name = PHASES[nextPhase];
    replies.push({
      tone: "trade",
      mono: true,
      text: fmtTg(`${name}  +${pct.toFixed(2)}%`, [
        `Pair          ${pair}`,
        `Unrealized    +${pct.toFixed(2)}%`,
        `Trail         ${((pos.trailingDistance / price) * 100).toFixed(2)}%`,
        `Stop          ${pxFmt(pos.trailingStop)}`,
        `Locked        ≈ ${locked >= 0 ? "+" : ""}${locked.toFixed(2)}%`,
        `Pattern       ${pos.pattern ?? "n/a"}`,
        "Goal          Profit locked. Distance is SACRED.",
      ]),
    });
  }

  if (price <= pos.stopLoss && pos.rescueCount >= 5 && pos.trailingStop < pos.entry && price <= pos.trailingStop * 1.01 && price < pos.entry) {
    bot.online = false;
    bot.lastSeen = now;
    replies.push({
      tone: "alert",
      mono: true,
      text: `BOT SHUTDOWN – POSITION KEPT\n${pair}\nReason: 5/5 rescues used and price reached TS+1% under the entry. Loss sell blocked.\nNo sell was sent. Bring the bot back online when you want this trade to continue.`,
    });
    return;
  }

  const rescueRemaining = st.rescuePool - pos.rescueUsed;
  const rescueTrigger = pos.trailingStop * 1.004;
  const canRescue =
    pos.trailingStop < pos.entry &&
    price <= pos.entry * 1.002 &&
    price <= rescueTrigger &&
    (pos.rescueCount < 5 || pos.rescueDipActive) &&
    rescueRemaining > 5 &&
    pct < 0.4;

  if (canRescue && replies.length === 0) {
    let count = pos.rescueCount + 1;
    if (count === 5 && !pos.rescueDipActive) {
      pos.rescueDipActive = true;
      pos.rescueDipLevel = price * 1.014;
      replies.push({
        tone: "alert",
        mono: true,
        text: `RESCUE TRAILING DIP ACTIVATED (5th order)\nDip level: ${pxFmt(pos.rescueDipLevel)}\nCurrent: ${pxFmt(price)}\nThe buy waits for a rebound.`,
      });
      return;
    }
    if (pos.rescueDipActive && pos.rescueDipLevel && price < pos.rescueDipLevel) {
      const nextLevel = price * 1.014;
      if (nextLevel < pos.rescueDipLevel) pos.rescueDipLevel = nextLevel;
      return;
    }
    if (count === 5 && pos.rescueDipActive && pos.rescueDipLevel && price < pos.rescueDipLevel) return;
    const factors = [0.5, 0.2, 0.3, 0.4, 0.9];
    let spend = rescueRemaining * factors[Math.min(count, 5) - 1];
    spend = Math.min(spend, rescueRemaining, bal(bot, lane).free);
    spend = Math.floor(spend * 100) / 100;
    if (spend < 5) {
      bot.online = false;
      bot.lastSeen = now;
      replies.push({
        tone: "alert",
        mono: true,
        text: `BOT SHUTDOWN – POSITION KEPT\n${pair}\nRescue #${count} needs at least 5 ${lane} but the wallet can pay ${spend.toFixed(2)}. Buy was not sent.`,
      });
      return;
    }
    const qty = spend / price;
    addFree(bot, lane, -spend);
    addFree(bot, pair.split("/")[0], qty);
    const oldAmt = pos.amount;
    const newAvg = (pos.entry * oldAmt + price * qty) / (oldAmt + qty);
    pos.amount += qty;
    pos.entry = newAvg;
    pos.rescueCount = count;
    pos.rescueUsed += spend;
    const t = targetsFor(newAvg, true, price);
    pos.primary = t.primary;
    pos.secondary = t.secondary;
    pos.stopLoss = t.stopLoss;
    pos.trailingDistance = t.trailingDistance;
    pos.trailingStop = t.trailingStop;
    pos.rescueDipActive = false;
    pos.rescueDipLevel = null;
    replies.push({
      tone: "alert",
      mono: true,
      text: `RESCUE TRADE #${count} done on ${pair}\nLoss was ${pct.toFixed(2)}%\nBought $${spend.toFixed(2)} ${lane} @ ${pxFmt(price)}\nNew avg entry: ${pxFmt(newAvg)}\nRescue pool left: $${(st.rescuePool - pos.rescueUsed).toFixed(2)}`,
    });
    return;
  }

  if (price <= pos.trailingStop || price <= pos.stopLoss) {
    const why = price <= pos.stopLoss ? "STOP-LOSS SELL" : "TRAILING-STOP SELL";
    closePosition(bot, lane, price, why, now, replies);
  }
}

function manageIsaac(bot: Bot, now: number, replies: Reply[]) {
  const isaac = bot.isaac;
  if (isaac.paused || now < isaac.cooldownUntil) return;
  const price = priceOf(bot, isaac.symbol);
  if (!price) return;
  const base = isaac.symbol.split("/")[0];
  const n = isaac.orders.length;
  const total = isaac.orders.reduce((s, o) => s + o.size, 0);
  const avg = total > 0 ? isaac.orders.reduce((s, o) => s + o.size * o.entry, 0) / total : 0;
  const last = n ? isaac.orders[n - 1].entry : price;

  if (n > 0 && avg > 0 && price >= avg * (1 + isaacDynamicTp(n) / 100)) {
    const cost = total * avg;
    const proceeds = total * price;
    const profit = proceeds - cost;
    addFree(bot, base, -Math.min(bal(bot, base).free, total));
    addFree(bot, "USDT", proceeds);
    isaac.virtualUsdt = Math.min(isaac.allocated, isaac.virtualUsdt + proceeds);
    isaac.orders = [];
    isaac.trailingStop = null;
    isaac.dipActive = false;
    isaac.cooldownUntil = now + 30_000;
    bot.history.push({
      ts: now,
      type: "isaac_profit",
      amount: profit,
      invested: cost,
      profitPct: (profit / cost) * 100,
      orderInfo: `Orders: ${n}`,
      lane: "ISAAC",
    });
    laneOf(bot, "USDT").allocated = Math.max(100, laneOf(bot, "USDT").allocated + profit);
    replies.push({
      tone: "trade",
      mono: true,
      text: `ISAAC DCA TP Success (+${isaacDynamicTp(n)}%)\nSold ${total.toFixed(4)} ${base} @ ${pxFmt(price)}\nPnL +$${profit.toFixed(2)}\nCycle reset to 0/7. Profit swept into the main USDT pool.`,
    });
    return;
  }

  if (n >= 7 && isaac.trailingStop != null && price <= isaac.trailingStop) {
    const cost = total * avg;
    const proceeds = total * price;
    const profit = proceeds - cost;
    addFree(bot, base, -Math.min(bal(bot, base).free, total));
    addFree(bot, "USDT", proceeds);
    isaac.orders = [];
    isaac.trailingStop = null;
    isaac.cooldownUntil = now + 30_000;
    bot.history.push({
      ts: now,
      type: "isaac_profit",
      amount: profit,
      invested: cost,
      profitPct: cost ? (profit / cost) * 100 : 0,
      orderInfo: `Orders: ${n}`,
      lane: "ISAAC",
    });
    replies.push({
      tone: "trade",
      mono: true,
      text: `ISAAC TRAILING STOP HIT\nSold ${total.toFixed(4)} ${base} @ ${pxFmt(price)}\nPnL ${profit >= 0 ? "+" : ""}$${profit.toFixed(2)}`,
    });
    return;
  }

  if (n >= 7 && isaac.trailingStop == null) {
    isaac.trailingDistance = price * 0.02;
    isaac.trailingStop = price - isaac.trailingDistance;
    replies.push({
      tone: "alert",
      text: `TRAILING STOP ACTIVATED\nIsaac is 7/7. Stop ${pxFmt(isaac.trailingStop)} (2% under ${pxFmt(price)}).`,
    });
    return;
  }

  if (n < 7 && replies.length === 0 && Math.random() < 0.18) {
    const need = isaacNextDrop(n);
    const drop = last > 0 ? ((last - price) / last) * 100 : 0;
    if (n === 0 || drop >= need) {
      const quote = bal(bot, "USDT").free;
      let buy = n === 0 ? 5000 : isaac.initial * Math.pow(1.5, n);
      buy = Math.min(buy, isaac.virtualUsdt, quote);
      buy = Math.floor(buy * 100) / 100;
      if (buy >= 100) {
        const qty = buy / price;
        addFree(bot, "USDT", -buy);
        addFree(bot, base, qty);
        isaac.virtualUsdt -= buy;
        isaac.orders.push({ entry: price, size: qty });
        isaac.cooldownUntil = now + 35_000;
        replies.push({
          tone: "trade",
          text: `ISAAC DCA #${n + 1}: Bought ${qty.toFixed(4)} ${base} @ ${pxFmt(price)} ($${buy.toFixed(2)})`,
        });
      }
    }
  }
}

export function tickBot(bot: Bot, now: number): { bot: Bot; replies: Reply[] } {
  const next: Bot = structuredClone(bot);
  const replies: Reply[] = [];
  for (const base of Object.keys(next.prices)) {
    const anchor = next.anchors[base] || next.prices[base];
    const shock = (Math.random() - 0.47) * 0.0042;
    let px = next.prices[base] * (1 + shock);
    const band = anchor * 0.14;
    px = Math.min(anchor + band, Math.max(anchor * 0.08, Math.max(anchor - band, px)));
    next.prices[base] = px;
    if (!next.series[base]) next.series[base] = [];
    next.series[base].push(px);
    if (next.series[base].length > 80) next.series[base].shift();
  }
  managePosition(next, "USDT", now, replies);
  if (replies.length === 0) managePosition(next, "USDC", now, replies);
  if (replies.length === 0) manageIsaac(next, now, replies);
  if (replies.length === 0) {
    for (const lane of ["USDT", "USDC"] as Lane[]) {
      const st = laneOf(next, lane);
      if (!st.symbol || st.position) continue;
      const price = priceOf(next, st.symbol);
      if (!price) continue;
      const ind = indicators(next, st.symbol, price);
      if (ind.score >= 86 && Math.random() < 0.22) {
        openManaged(next, lane, price, "EMA Momentum Alignment (Elite)", now, replies);
        break;
      }
    }
  }
  return { bot: next, replies };
}

export function pushReplies(
  messages: Message[],
  replies: Reply[],
  now: number,
): { messages: Message[]; unreadAdd: number } {
  const extra: Message[] = replies.map((r) => ({
    id: uid("m"),
    from: r.tone === "service" ? "service" : "bot",
    text: r.text,
    ts: now,
    tone: r.tone,
    mono: r.mono,
  }));
  const unreadAdd = extra.filter((m) => m.from === "bot").length;
  const merged = [...messages, ...extra];
  return { messages: merged.length > 500 ? merged.slice(-500) : merged, unreadAdd };
}

function msg(from: Message["from"], text: string, ts: number, extra?: Partial<Message>): Message {
  return { id: uid("m"), from, text, ts, ...extra };
}

function freshLane(allocated: number): LaneState {
  return { symbol: null, lastSymbol: null, allocated, rescuePool: 20000, position: null };
}

export function createBot(input: {
  name: string;
  exchange: Exchange;
  online?: boolean;
  now?: number;
  source?: "engine" | "bridge";
  bridgePort?: number;
  scriptPath?: string;
  pythonPath?: string;
  commands?: CommandSpec[];
}): Bot {
  const now = input.now ?? Date.now();
  const bot: Bot = {
    id: uid("bot"),
    name: input.name.trim() || "Bot",
    exchange: input.exchange,
    online: input.online ?? true,
    unread: 0,
    lastSeen: now,
    lanes: { USDT: freshLane(5000), USDC: freshLane(5000) },
    isaac: {
      symbol: "NEAR/USDT",
      orders: [],
      virtualUsdt: 36500,
      allocated: 36500,
      initial: 1000,
      paused: false,
      trailingStop: null,
      trailingDistance: null,
      dipActive: false,
      dipLevel: null,
      dipDistance: null,
      cooldownUntil: now + 60_000,
    },
    wallet: {
      USDT: { free: 15000, locked: 0 },
      USDC: { free: 8000, locked: 0 },
    },
    history: [],
    conversation: null,
    prices: {},
    anchors: {},
    series: {},
    messages: [],
    inbox: [],
    typing: false,
    entryCooldownUntil: now + 25_000,
    source: input.source ?? "engine",
    bridgePort: input.bridgePort,
    scriptPath: input.scriptPath,
    pythonPath: input.pythonPath,
    commands: input.commands ?? [...COMMANDS],
  };
  for (const base of BASES) ensureBase(bot, base);
  bot.messages.push(
    msg(
      "service",
      `${bot.name} is online on ${bot.exchange}. USDT uses /pair. USDC uses /pair2. Isaac watches NEAR/USDT.`,
      now,
      { tone: "service" },
    ),
  );
  return bot;
}

export function makeLocalBot(now = Date.now()): Bot {
  const bot = createBot({
    name: "ABinanceTradingBot (local)",
    exchange: "Binance",
    online: false,
    now,
    source: "bridge",
    bridgePort: 47832,
    commands: [...COMMANDS],
  });
  bot.lanes.USDT = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
  bot.lanes.USDC = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
  bot.isaac.symbol = "";
  bot.isaac.orders = [];
  bot.isaac.virtualUsdt = 0;
  bot.isaac.allocated = 0;
  bot.wallet = {};
  bot.history = [];
  bot.messages = [
    {
      id: uid("m"),
      from: "service",
      text: "Real local-script chat. Open Details and choose Connect / start script to run this bot through WIRE. Live notifications and command replies appear here; this chat does not simulate trades.",
      ts: now,
      tone: "service",
    },
  ];
  return bot;
}

export function seedBots(now = Date.now()): Bot[] {
  return [makeLocalBot(now)];
}

export function previewLine(bot: Bot): string {
  if (bot.typing) return "typing...";
  const last = [...bot.messages].reverse().find((m) => m.from !== "service") ?? bot.messages[bot.messages.length - 1];
  if (!last) return bot.online ? "online" : "offline";
  const who = last.from === "me" ? "You: " : "";
  return (who + last.text).replace(/\s+/g, " ").slice(0, 86);
}

export function laneQuotes(bot: Bot): { pair: string; price: number; pnl: number | null }[] {
  const out: { pair: string; price: number; pnl: number | null }[] = [];
  for (const lane of ["USDT", "USDC"] as Lane[]) {
    const st = bot.lanes[lane];
    if (!st.symbol) continue;
    const price = priceOf(bot, st.symbol);
    if (!price) continue;
    const pnl = st.position ? ((price - st.position.entry) / st.position.entry) * 100 : null;
    out.push({ pair: st.symbol, price, pnl });
  }
  return out;
}
