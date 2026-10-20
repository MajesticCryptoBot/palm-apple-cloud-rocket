import { i as __toESM } from "../_runtime.mjs";
import { K as require_react, b as require_jsx_runtime } from "../_libs/@tanstack/react-router+[...].mjs";
import { a as Send, c as PanelRight, d as Check, l as Clock, n as VolumeX, o as Search, r as Volume2, s as Plus, t as X, u as ChevronLeft } from "../_libs/lucide-react.mjs";
import { n as create, t as persist } from "../_libs/zustand.mjs";
//#region node_modules/.nitro/vite/services/ssr/assets/routes-tcXzxyov.js
var import_react = /* @__PURE__ */ __toESM(require_react());
var import_jsx_runtime = require_jsx_runtime();
var COMMANDS = [
	{
		name: "/pair",
		hint: "Set the USDT pair",
		group: "USDT"
	},
	{
		name: "/buy_price",
		hint: "Register a position you already hold",
		group: "USDT"
	},
	{
		name: "/mb",
		hint: "Manual market buy",
		group: "USDT"
	},
	{
		name: "/status",
		hint: "Full status panel",
		group: "USDT"
	},
	{
		name: "/balance",
		hint: "Spot wallet",
		group: "USDT"
	},
	{
		name: "/price",
		hint: "Live price",
		group: "USDT"
	},
	{
		name: "/compound_status",
		hint: "Compounding panel",
		group: "USDT"
	},
	{
		name: "/magic_sell",
		hint: "Emergency sell this pair only",
		group: "USDT",
		danger: true
	},
	{
		name: "/reset_state",
		hint: "Clear the USDT lane",
		group: "USDT",
		danger: true
	},
	{
		name: "/pair2",
		hint: "Set the USDC pair",
		group: "USDC"
	},
	{
		name: "/buy_price2",
		hint: "Register a USDC position",
		group: "USDC"
	},
	{
		name: "/mb2",
		hint: "Manual market buy in USDC",
		group: "USDC"
	},
	{
		name: "/status2",
		hint: "USDC status panel",
		group: "USDC"
	},
	{
		name: "/balance2",
		hint: "USDC spot wallet",
		group: "USDC"
	},
	{
		name: "/price2",
		hint: "USDC pair price",
		group: "USDC"
	},
	{
		name: "/compound_status2",
		hint: "USDC compounding panel",
		group: "USDC"
	},
	{
		name: "/magic_sell2",
		hint: "Emergency sell the USDC pair",
		group: "USDC",
		danger: true
	},
	{
		name: "/reset_state2",
		hint: "Clear the USDC lane",
		group: "USDC",
		danger: true
	},
	{
		name: "/isaac_status",
		hint: "Isaac DCA panel",
		group: "Isaac"
	},
	{
		name: "/emergency_isaac",
		hint: "Sell Isaac and reset the cycle",
		group: "Isaac",
		danger: true
	},
	{
		name: "/cancel",
		hint: "Abort the current question",
		group: "Session"
	}
];
var BASES = [
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
	"PEPE"
];
var ANCHORS = {
	BTC: 67240,
	ETH: 3284.5,
	SOL: 148.22,
	XRP: .5421,
	NEAR: 4.821,
	DOGE: .1284,
	BNB: 592.3,
	ADA: .3612,
	AVAX: 27.44,
	LINK: 13.82,
	SUI: 2.146,
	LTC: 86.4,
	DOT: 4.22,
	TON: 5.31,
	PEPE: 912e-8
};
var PHASES = [
	"RUN",
	"BREATHE",
	"LOCK",
	"STEEL",
	"HARVEST",
	"MOONSHOT"
];
var PHASE_DIST = [
	.048,
	.008,
	.006,
	.008,
	.008,
	.015
];
function uid(prefix = "id") {
	return `${prefix}_${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-4)}`;
}
function money(n, d = 2) {
	return n.toLocaleString("en-US", {
		minimumFractionDigits: d,
		maximumFractionDigits: d
	});
}
function pxFmt(n) {
	if (!Number.isFinite(n)) return "N/A";
	if (n >= 1e3) return n.toLocaleString("en-US", {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2
	});
	if (n >= 1) return n.toFixed(4);
	if (n >= .01) return n.toFixed(6);
	return n.toFixed(8);
}
function bal(bot, ccy) {
	return bot.wallet[ccy] ?? {
		free: 0,
		locked: 0
	};
}
function setBal(bot, ccy, free, locked) {
	const prev = bal(bot, ccy);
	bot.wallet[ccy] = {
		free: Math.max(0, free),
		locked: locked ?? prev.locked
	};
}
function addFree(bot, ccy, delta) {
	const b = bal(bot, ccy);
	setBal(bot, ccy, b.free + delta, b.locked);
}
function priceOf(bot, pair) {
	const base = pair.split("/")[0];
	const q = pair.split("/")[1];
	const raw = bot.prices[base];
	if (!raw || raw <= 0) return null;
	return q === "USDC" ? raw * .9998 : raw;
}
function ensureBase(bot, base, around) {
	if (!bot.prices[base]) {
		const anchor = around && around > 0 ? around : ANCHORS[base] ?? 1;
		bot.anchors[base] = anchor;
		bot.prices[base] = anchor;
	}
	if (!bot.series[base] || bot.series[base].length < 20) {
		const start = bot.prices[base] * .985;
		const arr = [];
		let p = start;
		for (let i = 0; i < 48; i++) {
			p *= 1 + Math.sin(i / 4) * .0018;
			arr.push(p);
		}
		arr.push(bot.prices[base]);
		bot.series[base] = arr;
	}
}
function laneOf(bot, lane) {
	return bot.lanes[lane];
}
function otherLane(lane) {
	return lane === "USDT" ? "USDC" : "USDT";
}
function example(lane) {
	return lane === "USDC" ? "BTC/USDC" : "BTC/USDT";
}
function pairCmd(lane) {
	return lane === "USDC" ? "/pair2" : "/pair";
}
function sellCmd(lane) {
	return lane === "USDC" ? "/magic_sell2" : "/magic_sell";
}
function parsePair(raw, lane) {
	let s = raw.trim().toUpperCase().replace(/-/g, "/");
	if (!s.includes("/") && (s.endsWith("USDT") || s.endsWith("USDC"))) {
		const q = s.endsWith("USDC") ? "USDC" : "USDT";
		s = `${s.slice(0, -4)}/${q}`;
	}
	const parts = s.split("/");
	if (parts.length !== 2 || !parts[0]) return {
		ok: false,
		why: "invalid"
	};
	if (parts[1] !== lane) return {
		ok: false,
		why: "quote"
	};
	if (!ANCHORS[parts[0]]) return {
		ok: false,
		why: "invalid"
	};
	return {
		ok: true,
		pair: `${parts[0]}/${lane}`
	};
}
function targetsFor(entry, rescue = false, rescuePx) {
	const primary = entry * (rescue ? 1.035 : 1.045);
	const secondary = entry * (rescue ? 1.015 : 1.025);
	const basis = rescue && rescuePx && rescuePx > 0 ? rescuePx : entry;
	const stop = rescue ? basis * .9019 : entry * .9319;
	const dist = rescue ? basis * .0875 : entry * .0625;
	let trailingStop = basis - dist;
	const stopLoss = stop > trailingStop ? trailingStop * .99 : stop;
	if (trailingStop <= 0) trailingStop = basis * .9;
	return {
		primary,
		secondary,
		stopLoss,
		trailingStop,
		trailingDistance: dist
	};
}
function makePosition(entry, amount, pattern) {
	return {
		entry,
		amount,
		...targetsFor(entry, false),
		rescueCount: 0,
		rescueUsed: 0,
		scaleCount: 0,
		phase: 0,
		pattern,
		rescueDipActive: false,
		rescueDipLevel: null
	};
}
function ema(values, period) {
	if (!values.length) return 0;
	const k = 2 / (period + 1);
	let e = values[0];
	for (const v of values) e = v * k + e * (1 - k);
	return e;
}
function rsi(values) {
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
	return 100 - 100 / (1 + g / l);
}
function indicators(bot, pair, price) {
	const base = pair.split("/")[0];
	ensureBase(bot, base, price);
	const closes = bot.series[base];
	const e5 = ema(closes, 5);
	const e9 = ema(closes, 9);
	const e13 = ema(closes, 13);
	const e21 = ema(closes, 21);
	const e50 = ema(closes, 50);
	const r = rsi(closes);
	const atr = Math.max(price * .008, Math.abs(closes[closes.length - 1] - closes[Math.max(0, closes.length - 14)]) / 6);
	const macd = e9 - e21;
	const signal = macd * .82;
	const hist = macd - signal;
	const vwap = closes.slice(-20).reduce((a, b) => a + b, 0) / Math.min(20, closes.length);
	const support = Math.min(...closes.slice(-20));
	const fib = support + .618 * (Math.max(...closes.slice(-20)) - support);
	let score = 0;
	if (e5 > e9 && e9 > e13 && e13 > e21 && e21 > e50 * .995) score += 40;
	else if (e9 > e21) score += 24;
	if (r > 48 && r < 72) score += 18;
	if (price > Math.max(e5, e9, e21)) score += 12;
	if (hist > 0) score += 10;
	if (r > 74) score -= 18;
	if (price > e21 * 1.03) score -= 10;
	score = Math.max(0, Math.min(99, Math.round(score)));
	return {
		e5,
		e9,
		e13,
		e21,
		e50,
		r,
		atr,
		macd,
		signal,
		hist,
		vwap,
		support,
		fib,
		score
	};
}
function fmtTg(title, rows) {
	return [`━━ ${title} ━━`, ...rows].join("\n");
}
function phaseIndex(pct) {
	if (pct >= 10.5) return 5;
	if (pct >= 7.8) return 4;
	if (pct >= 5.8) return 3;
	if (pct >= 4.2) return 2;
	if (pct >= 1.8) return 1;
	return 0;
}
function trackedAmount(bot, pair) {
	const st = laneOf(bot, pair.endsWith("USDC") ? "USDC" : "USDT");
	if (st.symbol === pair && st.position) return st.position.amount;
	return 0;
}
function sellableBase(bot, pair) {
	const base = pair.split("/")[0];
	const free = bal(bot, base).free;
	const other = laneOf(bot, otherLane(pair.endsWith("USDC") ? "USDC" : "USDT"));
	const otherBase = other.symbol?.split("/")[0];
	const otherAmt = other.position && otherBase === base ? other.position.amount : 0;
	if (otherAmt > 0) {
		const tracked = trackedAmount(bot, pair);
		return Math.min(free, tracked > 0 ? tracked : Math.max(0, free - otherAmt));
	}
	return free;
}
function recordMain(bot, lane, profit, invested, now) {
	const pct = invested > 0 ? profit / invested * 100 : 0;
	bot.history.push({
		ts: now,
		type: "main_profit",
		amount: profit,
		invested,
		profitPct: pct,
		lane
	});
	if (bot.history.length > 400) bot.history.splice(0, bot.history.length - 400);
	const st = laneOf(bot, lane);
	st.allocated = Math.max(100, st.allocated + profit);
}
function statusText(bot, lane) {
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
		const pct = (price - pos.entry) / pos.entry * 100;
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
		`ATR ${pxFmt(ind.atr)} (${(ind.atr / price * 100).toFixed(2)}%)`,
		`MACD ${ind.macd.toFixed(4)} / Signal ${ind.signal.toFixed(4)} / Hist ${ind.hist.toFixed(4)}`,
		`VWAP ${pxFmt(ind.vwap)}`,
		`Support ${pxFmt(ind.support)}`,
		`Fib 61.8% ${pxFmt(ind.fib)}`
	].join("\n");
	let orders = "None";
	if (pos) {
		const distPct = pos.trailingDistance / price * 100;
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
			`Pattern: ${pos.pattern ?? "n/a"}`
		];
		if (pos.rescueDipActive && pos.rescueDipLevel) lines.push(`Rescue trailing dip: ACTIVE @ ${pxFmt(pos.rescueDipLevel)}`);
		orders = lines.join("\n");
	}
	const radar = ind.score >= 65 ? `Valid Patterns (>=65%): 1 found\n\nPATTERN 6: EMA Momentum Alignment (Elite)\nMatch: ${ind.score}%` : "No Qualified Pattern to trigger For Now";
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
		`BTC Price: ${btc ? "$" + pxFmt(btc) : "N/A"}`
	].join("\n");
}
function balanceText(bot, lane) {
	const st = laneOf(bot, lane);
	const shown = st.lastSymbol || st.symbol;
	if (!shown) return `No pair set. Use ${pairCmd(lane)}`;
	const base = shown.split("/")[0];
	const b = bal(bot, base);
	const q = bal(bot, lane);
	return `Spot Wallet: ${b.free.toFixed(8)} ${base} (free), ${b.locked.toFixed(8)} ${base} (locked), ${q.free.toFixed(2)} ${lane} (free), ${q.locked.toFixed(2)} ${lane} (locked)`;
}
function priceText(bot, lane) {
	const st = laneOf(bot, lane);
	const shown = st.lastSymbol || st.symbol;
	if (!shown) return `No pair set. Use ${pairCmd(lane)}`;
	const price = priceOf(bot, shown);
	if (!price) return `Error fetching price for ${shown}`;
	return `${shown}: $${pxFmt(price)}`;
}
function compoundText(bot, lane) {
	if (lane === "USDC") {
		const profits = bot.history.filter((e) => e.type === "main_profit" && e.lane === "USDC");
		const total = profits.reduce((s, e) => s + e.amount, 0);
		const alloc = laneOf(bot, "USDC").allocated;
		const lines = [
			"COMPOUNDING STATUS PANEL (USDC)",
			"",
			`Total Wallet USDC     : $${money(bal(bot, "USDC").free)}`,
			"",
			`1. USDC Lane Asset    : $${money(alloc)}   (+$${money(total)} growth)`,
			"   (Started at 5000)",
			"   This lane does not include Isaac DCA.",
			"",
			`2. Profit from USDC lane: $${money(total)}`,
			`3. USDC lane trades     : ${profits.length} trades`,
			"",
			laneOf(bot, "USDC").symbol ? `Pair: ${laneOf(bot, "USDC").symbol}` : "Pair: not set. Use /pair2",
			""
		];
		const pos = laneOf(bot, "USDC").position;
		const sym = laneOf(bot, "USDC").symbol;
		if (pos && sym) lines.push(`Open: ${sym} | Invested $${money(pos.entry * pos.amount)}`, "");
		lines.push("4. Last 30 USDC Lane Trades:");
		if (!profits.length) lines.push("   (none yet)");
		else for (const t of profits.slice(-30).reverse()) {
			const time = new Date(t.ts).toISOString().slice(0, 16).replace("T", " ");
			if (t.invested != null && t.profitPct != null) lines.push(`   ${time} | $${money(t.invested)} -> TP: +$${t.amount.toFixed(2)} / ${t.profitPct.toFixed(2)}%`);
			else lines.push(`   ${time} | Profit: +$${t.amount.toFixed(2)}`);
		}
		return lines.join("\n");
	}
	const main = bot.history.filter((e) => e.type === "main_profit" && e.lane === "USDT");
	const isaac = bot.history.filter((e) => e.type === "isaac_profit");
	const mainSum = main.reduce((s, e) => s + e.amount, 0);
	const isaacSum = isaac.reduce((s, e) => s + e.amount, 0);
	const growth = mainSum + isaacSum;
	const lines = [
		"COMPOUNDING STATUS PANEL",
		"",
		`Total Wallet USDT     : $${money(bal(bot, "USDT").free)}`,
		"",
		`1. Main Bot Asset     : $${money(laneOf(bot, "USDT").allocated)}   (+$${money(growth)} Total Growth)`,
		"   (Started at 5000)",
		`   ISAAC DCA Contribution : +$${money(isaacSum)}`,
		`   Main Bot Contribution  : +$${money(mainSum)}`,
		"",
		`2. ISAAC DCA Asset    : $${money(bot.isaac.allocated)}`,
		`   Initial Buy Size   : $${bot.isaac.initial.toFixed(0)}`,
		"",
		`3. Profit from Main Bot : $${money(mainSum)} (${(mainSum / 5e3 * 100).toFixed(1)}% from initial)`,
		`4. Profit from ISAAC DCA: $${money(isaacSum)}`,
		`5. Combined Profit      : $${money(mainSum + isaacSum)}`,
		"",
		`6. Main Bot Trades    : ${main.length} trades`,
		`7. ISAAC DCA Trades   : ${isaac.length} trades`,
		""
	];
	const pos = laneOf(bot, "USDT").position;
	const sym = laneOf(bot, "USDT").symbol;
	if (pos && sym) lines.push("Open Main Bot Positions:", `   OPEN ${sym} | Invested: $${money(pos.entry * pos.amount)}`, "");
	if (bot.isaac.orders.length) {
		const cost = bot.isaac.orders.reduce((s, o) => s + o.size * o.entry, 0);
		lines.push("Open ISAAC DCA Positions:", `   OPEN | Invested: $${money(cost)} (${bot.isaac.orders.length} orders)`, "");
	}
	lines.push("8. Last 30 Main Bot Trades:");
	if (!main.length) lines.push("   (none yet)");
	else for (const t of main.slice(-30).reverse()) {
		const time = new Date(t.ts).toISOString().slice(0, 16).replace("T", " ");
		if (t.invested != null && t.profitPct != null) lines.push(`   ${time} | $${money(t.invested)} -> TP: +$${t.amount.toFixed(2)} / ${t.profitPct.toFixed(2)}%`);
		else lines.push(`   ${time} | Profit: +$${t.amount.toFixed(2)}`);
	}
	lines.push("", "9. Last 30 ISAAC DCA Trades:");
	if (!isaac.length) lines.push("   (none yet)");
	else for (const t of isaac.slice(-30).reverse()) {
		const time = new Date(t.ts).toISOString().slice(0, 16).replace("T", " ");
		const info = t.orderInfo ? ` (${t.orderInfo})` : "";
		if (t.invested != null && t.profitPct != null) lines.push(`   ${time} | $${money(t.invested)}${info} -> TP: +$${t.amount.toFixed(2)} / ${t.profitPct.toFixed(2)}%`);
		else lines.push(`   ${time} | Profit: +$${t.amount.toFixed(2)}`);
	}
	return lines.join("\n");
}
function isaacDynamicTp(n) {
	if (n <= 1) return 2.5;
	if (n === 2) return 2.8;
	if (n === 3) return 3.2;
	if (n === 4) return 3.7;
	if (n === 5) return 4.2;
	if (n === 6) return 4.7;
	return 5.2;
}
function isaacNextDrop(n) {
	if (n <= 0) return 0;
	if (n === 1) return 3;
	if (n === 2) return 5;
	if (n === 3) return 8;
	if (n === 4) return 24;
	if (n === 5) return 32;
	return 40;
}
function isaacStatusText(bot) {
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
	const pnlPct = avg > 0 ? (price - avg) / avg * 100 : 0;
	const b = bal(bot, base);
	const q = bal(bot, "USDT");
	const used = b.free * price;
	const available = Math.max(0, isaac.allocated - used);
	const virtual = Math.min(available, isaac.virtualUsdt);
	const dcaValue = b.free * price;
	const port = q.free + dcaValue;
	const weight = port > 0 ? dcaValue / port * 100 : 0;
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
		`Trailing Dip: ${isaac.dipActive ? "ACTIVE" : "Inactive"}`
	];
	if (isaac.dipActive && isaac.dipLevel) lines.push(`  Dip Level: $${pxFmt(isaac.dipLevel)}`);
	lines.push("", `Trailing Stop: ${isaac.trailingStop != null ? "ACTIVE" : "Inactive"}`);
	if (isaac.trailingStop != null) lines.push(`  Stop Level: $${pxFmt(isaac.trailingStop)}`);
	lines.push("", "Dynamic Drop Settings:", "  Order 1  Direct Buy  5000 USDT", "  Order 2  -3%   1500 USDT", "  Order 3  -5%   2250 USDT", "  Order 4  -8%   3375 USDT", "  Order 5  -24%  5062.50 USDT", "  Order 6  -32%  7593.75 USDT", "  Order 7  Trailing Dip @ -40%  11390.63 USDT", "", "Dynamic TP Settings:", "  Order 1  +2.5%", "  Order 2  +2.8%", "  Order 3  +3.2%", "  Order 4  +3.7%", "  Order 5  +4.2%", "  Order 6  +4.7%", "  Order 7  +5.2%");
	return lines.join("\n");
}
function setPair(bot, lane, raw, replies) {
	const parsed = parsePair(raw, lane);
	if (!parsed.ok) {
		if (parsed.why === "quote") replies.push({
			tone: "normal",
			text: lane === "USDC" ? `/pair2 only accepts a USDC pair (e.g. ${example(lane)}). USDT pairs use /pair.` : `/pair only accepts a USDT pair (e.g. ${example(lane)}). USDC pairs use /pair2.`
		});
		else replies.push({
			tone: "normal",
			text: `Invalid pair: ${raw.toUpperCase()}. Try ${example(lane)}.`
		});
		return;
	}
	const st = laneOf(bot, lane);
	if (st.position && st.symbol && st.symbol !== parsed.pair) {
		replies.push({
			tone: "alert",
			text: `${st.symbol} is still open on this lane. Close it with ${sellCmd(lane)} before switching pairs.`
		});
		return;
	}
	st.symbol = parsed.pair;
	st.lastSymbol = parsed.pair;
	ensureBase(bot, parsed.pair.split("/")[0]);
	bot.conversation = null;
	replies.push({
		tone: "normal",
		text: `${parsed.pair} pair added`
	});
}
function promptPair(bot, lane, replies) {
	bot.conversation = {
		kind: "pair",
		lane
	};
	replies.push({
		tone: "normal",
		text: `Enter trading pair (e.g., ${example(lane)})`
	});
}
function promptBuy(bot, lane, replies) {
	const ex = lane === "USDC" ? "SOL/USDC 150 2" : "BTC/USDT 80000 0.1";
	bot.conversation = {
		kind: "buy_price",
		lane
	};
	replies.push({
		tone: "normal",
		text: `Enter pair, buy price, and amount: <pair> <buy_price> <amount> (e.g., ${ex}). This command only affects ${pairCmd(lane)}.`
	});
}
function applyBuyPrice(bot, lane, args, replies, keepConversation) {
	const ex = lane === "USDC" ? "SOL/USDC 150 2" : "BTC/USDT 80000 0.1";
	const st = laneOf(bot, lane);
	if (!st.symbol) {
		replies.push({
			tone: "normal",
			text: lane === "USDC" ? "Set a trading pair with /pair2 first" : "Set a trading pair with /pair first"
		});
		if (!keepConversation) bot.conversation = null;
		return;
	}
	if (args.length !== 3) {
		replies.push({
			tone: "normal",
			text: `Use: <pair> <buy_price> <amount> (e.g., ${ex})`
		});
		if (keepConversation) bot.conversation = {
			kind: "buy_price",
			lane
		};
		return;
	}
	const parsed = parsePair(args[0], lane);
	if (!parsed.ok) {
		replies.push({
			tone: "normal",
			text: parsed.why === "quote" ? lane === "USDC" ? `/buy_price2 only accepts a USDC pair, got ${args[0].toUpperCase()}.` : `/buy_price only accepts a USDT pair, got ${args[0].toUpperCase()}.` : `Invalid pair: ${args[0].toUpperCase()}`
		});
		if (keepConversation) bot.conversation = {
			kind: "buy_price",
			lane
		};
		return;
	}
	if (parsed.pair !== st.symbol) {
		replies.push({
			tone: "normal",
			text: `${parsed.pair} is not the active pair. Current pair is ${st.symbol}.`
		});
		if (keepConversation) bot.conversation = {
			kind: "buy_price",
			lane
		};
		return;
	}
	const buy = Number(args[1]);
	const amount = Number(args[2]);
	if (!Number.isFinite(buy) || !Number.isFinite(amount)) {
		replies.push({
			tone: "normal",
			text: "Buy price and amount must be numbers"
		});
		if (keepConversation) bot.conversation = {
			kind: "buy_price",
			lane
		};
		return;
	}
	if (buy <= 0 || amount <= 0) {
		replies.push({
			tone: "normal",
			text: "Buy price and amount must be positive"
		});
		if (keepConversation) bot.conversation = {
			kind: "buy_price",
			lane
		};
		return;
	}
	const base = parsed.pair.split("/")[0];
	const held = bal(bot, base).free;
	if (amount > held + 1e-8) {
		replies.push({
			tone: "normal",
			text: `Insufficient ${base} balance: ${held.toFixed(8)} < ${amount.toFixed(8)}`
		});
		if (keepConversation) bot.conversation = {
			kind: "buy_price",
			lane
		};
		return;
	}
	const pos = makePosition(buy, amount, "Manual registration");
	const live = priceOf(bot, parsed.pair) ?? buy;
	pos.trailingDistance = Math.max(pos.trailingDistance, live * .048);
	pos.trailingStop = live - pos.trailingDistance;
	st.position = pos;
	bot.conversation = null;
	replies.push({
		tone: "trade",
		mono: true,
		text: `Position initialized for ${parsed.pair}: ${amount.toFixed(8)} ${base} at entry price $${pxFmt(buy)}\nPrimary $${pxFmt(pos.primary)}, Secondary $${pxFmt(pos.secondary)}, Stop-Loss $${pxFmt(pos.stopLoss)}, Trailing Stop $${pxFmt(pos.trailingStop)}`
	});
}
function promptMb(bot, lane, replies) {
	const st = laneOf(bot, lane);
	if (!st.symbol) {
		replies.push({
			tone: "normal",
			text: `No trading pair set. Use ${pairCmd(lane)} first.`
		});
		bot.conversation = null;
		return;
	}
	bot.conversation = {
		kind: "mb",
		lane
	};
	replies.push({
		tone: "normal",
		text: `Manual buy on ${st.symbol}\nSend the ${lane} amount (e.g. 1500)\n/cancel to abort`
	});
}
function applyMb(bot, lane, raw, replies) {
	const st = laneOf(bot, lane);
	let requested = Number(String(raw).replace(/,/g, "").trim());
	if (!Number.isFinite(requested)) {
		replies.push({
			tone: "normal",
			text: "Invalid amount. Send a number (e.g. 1500)."
		});
		bot.conversation = {
			kind: "mb",
			lane
		};
		return;
	}
	if (requested <= 0) {
		replies.push({
			tone: "normal",
			text: "Amount must be > 0."
		});
		bot.conversation = {
			kind: "mb",
			lane
		};
		return;
	}
	if (!st.symbol) {
		replies.push({
			tone: "normal",
			text: `No trading pair set. Use ${pairCmd(lane)} first.`
		});
		bot.conversation = null;
		return;
	}
	const price = priceOf(bot, st.symbol);
	if (!price) {
		replies.push({
			tone: "normal",
			text: `Cannot get current price for ${st.symbol}.`
		});
		bot.conversation = null;
		return;
	}
	const wallet = bal(bot, lane).free;
	const use = Math.floor(Math.min(requested, wallet) * 100) / 100;
	if (use < 10) {
		replies.push({
			tone: "alert",
			text: `Insufficient ${lane}: requested $${requested.toFixed(2)} | wallet $${wallet.toFixed(2)} | using $${use.toFixed(2)}`
		});
		bot.conversation = null;
		return;
	}
	const base = st.symbol.split("/")[0];
	const qty = use / price;
	addFree(bot, lane, -use);
	addFree(bot, base, qty);
	const orderId = String(8e8 + Math.floor(Math.random() * 1e8));
	bot.conversation = null;
	replies.push({
		tone: "trade",
		mono: true,
		text: `MANUAL MARKET BUY EXECUTED\n${base}: ${qty.toFixed(6)} @ ~${pxFmt(price)}\nRequested: $${requested.toFixed(2)} ${lane} | Used: $${use.toFixed(2)} | Wallet: $${bal(bot, lane).free.toFixed(2)}\nOrder ID: ${orderId}\n(No pattern targets or trailing stop set — manual buy)`
	});
}
function magicSell(bot, lane, replies, now) {
	const st = laneOf(bot, lane);
	const pair = st.symbol;
	if (!pair) {
		replies.push({
			tone: "normal",
			text: `No trading pair set (${pairCmd(lane)}). Nothing to sell.`
		});
		return;
	}
	const base = pair.split("/")[0];
	const qty = sellableBase(bot, pair);
	if (qty <= 1e-8) {
		replies.push({
			tone: "normal",
			text: `No ${base} available to sell.`
		});
		return;
	}
	const price = priceOf(bot, pair);
	if (!price) {
		replies.push({
			tone: "normal",
			text: `Cannot get price for ${pair}.`
		});
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
	const orderId = String(7e8 + Math.floor(Math.random() * 1e8));
	replies.push({
		tone: "trade",
		mono: true,
		text: `MAGIC SELL (EMERGENCY) EXECUTED\n${base}: ${soldQty.toFixed(6)} sold @ ~${pxFmt(price)}\nRecovered ≈ $${value.toFixed(2)} ${lane}\nOrder ID: ${orderId}\nISAAC DCA was NOT affected.`
	});
}
function resetLane(bot, lane, replies) {
	const st = laneOf(bot, lane);
	st.symbol = null;
	st.lastSymbol = null;
	st.position = null;
	replies.push({
		tone: "alert",
		text: lane === "USDC" ? "USDC lane reset. Set a new pair with /pair2." : "Bot state reset. Set new pair with /pair."
	});
}
function emergencyIsaac(bot, replies, now) {
	const base = bot.isaac.symbol.split("/")[0];
	const tracked = bot.isaac.orders.reduce((s, o) => s + o.size, 0);
	const qty = Math.min(bal(bot, base).free, tracked > 0 ? tracked : bal(bot, base).free);
	if (qty <= 1e-8) {
		replies.push({
			tone: "normal",
			text: `No ${base} balance available for ISAAC DCA to sell.`
		});
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
			profitPct: cost > 0 ? profit / cost * 100 : 0,
			orderInfo: `Orders: ${bot.isaac.orders.length}`,
			lane: "ISAAC"
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
		text: `EMERGENCY SELL SUCCESSFUL\nSold ${qty.toFixed(6)} ${base} @ ${pxFmt(price)}\nCycle reset to 0/7. New buy cycle will start soon.`
	});
}
function dispatchCommand(bot, text, replies, now) {
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
			replies.push({
				tone: "normal",
				mono: true,
				text: statusText(bot, "USDT")
			});
			return;
		case "/status2":
			replies.push({
				tone: "normal",
				mono: true,
				text: statusText(bot, "USDC")
			});
			return;
		case "/balance":
			replies.push({
				tone: "normal",
				mono: true,
				text: balanceText(bot, "USDT")
			});
			return;
		case "/balance2":
			replies.push({
				tone: "normal",
				mono: true,
				text: balanceText(bot, "USDC")
			});
			return;
		case "/price":
			replies.push({
				tone: "normal",
				text: priceText(bot, "USDT")
			});
			return;
		case "/price2":
			replies.push({
				tone: "normal",
				text: priceText(bot, "USDC")
			});
			return;
		case "/compound_status":
			replies.push({
				tone: "normal",
				mono: true,
				text: compoundText(bot, "ALL")
			});
			return;
		case "/compound_status2":
			replies.push({
				tone: "normal",
				mono: true,
				text: compoundText(bot, "USDC")
			});
			return;
		case "/isaac_status":
			replies.push({
				tone: "normal",
				mono: true,
				text: isaacStatusText(bot)
			});
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
			replies.push({
				tone: "service",
				text: "Nothing to cancel."
			});
			return;
		default: replies.push({
			tone: "normal",
			text: "Unknown command. Type / to open this bot's command list."
		});
	}
}
function answerConversation(bot, text, replies) {
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
function applyUserText(bot, text, now) {
	const next = structuredClone(bot);
	const replies = [];
	const trimmed = text.trim();
	if (!trimmed) return {
		bot: next,
		replies
	};
	if (trimmed.startsWith("/")) {
		const conv = next.conversation;
		if (trimmed.split(/\s+/)[0].toLowerCase() === "/cancel" && conv) {
			next.conversation = null;
			replies.push({
				tone: "service",
				text: conv.kind === "pair" ? "Pair setting cancelled" : "Cancelled."
			});
			return {
				bot: next,
				replies
			};
		}
		dispatchCommand(next, trimmed, replies, now);
		return {
			bot: next,
			replies
		};
	}
	if (next.conversation) {
		answerConversation(next, trimmed, replies);
		return {
			bot: next,
			replies
		};
	}
	replies.push({
		tone: "normal",
		text: "Send a command. Type / to see the list, the same way you would in Telegram."
	});
	return {
		bot: next,
		replies
	};
}
function closePosition(bot, lane, price, reason, now, replies) {
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
	bot.entryCooldownUntil = now + 45e3;
	replies.push({
		tone: profit >= 0 ? "trade" : "alert",
		mono: true,
		text: `${reason}\n${pair}\nSold ${qty.toFixed(6)} ${base} @ ${pxFmt(price)}\nPnL ${profit >= 0 ? "+" : ""}$${profit.toFixed(2)} (${invested > 0 ? (profit / invested * 100).toFixed(2) : "0.00"}%)\nPosition closed. Watching for the next pattern.`
	});
}
function openManaged(bot, lane, price, pattern, now, replies) {
	const st = laneOf(bot, lane);
	if (!st.symbol || st.position) return;
	if (now < bot.entryCooldownUntil) return;
	const quoteFree = bal(bot, lane).free;
	const budget = Math.min(st.allocated * .35, quoteFree * .45);
	const spend = Math.floor(budget * 100) / 100;
	if (spend < 50) return;
	const base = st.symbol.split("/")[0];
	const qty = spend / price;
	addFree(bot, lane, -spend);
	addFree(bot, base, qty);
	const pos = makePosition(price, qty, pattern);
	pos.trailingDistance = price * .048;
	pos.trailingStop = price - pos.trailingDistance;
	st.position = pos;
	bot.entryCooldownUntil = now + 2e4;
	replies.push({
		tone: "trade",
		mono: true,
		text: `PATTERN 6: EMA Momentum Alignment (Elite)\nMatch: 91%\n\nBuy Order Filled and Targets Set\n${base}: ${qty.toFixed(6)} at ${pxFmt(price)}\nPrimary: ${pxFmt(pos.primary)}\nSecondary: ${pxFmt(pos.secondary)}\nStop-Loss: ${pxFmt(pos.stopLoss)}\nTrailing Stop: ${pxFmt(pos.trailingStop)}`
	});
}
function managePosition(bot, lane, now, replies) {
	const st = laneOf(bot, lane);
	const pos = st.position;
	const pair = st.symbol;
	if (!pos || !pair) return;
	const price = priceOf(bot, pair);
	if (!price) return;
	const pct = (price - pos.entry) / pos.entry * 100;
	const nextPhase = phaseIndex(pct);
	if (pos.phase === 0) {
		const runDist = price * .048;
		if (pos.trailingDistance < price * .012 || Math.abs(pos.trailingDistance - runDist) / price > .02) pos.trailingDistance = runDist;
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
				`Trail         ${(pos.trailingDistance / price * 100).toFixed(2)}%`,
				`Stop          ${pxFmt(pos.trailingStop)}`,
				`Locked        ≈ ${locked >= 0 ? "+" : ""}${locked.toFixed(2)}%`,
				`Pattern       ${pos.pattern ?? "n/a"}`,
				"Goal          Profit locked. Distance is SACRED."
			])
		});
	}
	if (price <= pos.stopLoss && pos.rescueCount >= 5 && pos.trailingStop < pos.entry && price <= pos.trailingStop * 1.01 && price < pos.entry) {
		bot.online = false;
		bot.lastSeen = now;
		replies.push({
			tone: "alert",
			mono: true,
			text: `BOT SHUTDOWN – POSITION KEPT\n${pair}\nReason: 5/5 rescues used and price reached TS+1% under the entry. Loss sell blocked.\nNo sell was sent. Bring the bot back online when you want this trade to continue.`
		});
		return;
	}
	const rescueRemaining = st.rescuePool - pos.rescueUsed;
	const rescueTrigger = pos.trailingStop * 1.004;
	if (pos.trailingStop < pos.entry && price <= pos.entry * 1.002 && price <= rescueTrigger && (pos.rescueCount < 5 || pos.rescueDipActive) && rescueRemaining > 5 && pct < .4 && replies.length === 0) {
		let count = pos.rescueCount + 1;
		if (count === 5 && !pos.rescueDipActive) {
			pos.rescueDipActive = true;
			pos.rescueDipLevel = price * 1.014;
			replies.push({
				tone: "alert",
				mono: true,
				text: `RESCUE TRAILING DIP ACTIVATED (5th order)\nDip level: ${pxFmt(pos.rescueDipLevel)}\nCurrent: ${pxFmt(price)}\nThe buy waits for a rebound.`
			});
			return;
		}
		if (pos.rescueDipActive && pos.rescueDipLevel && price < pos.rescueDipLevel) {
			const nextLevel = price * 1.014;
			if (nextLevel < pos.rescueDipLevel) pos.rescueDipLevel = nextLevel;
			return;
		}
		if (count === 5 && pos.rescueDipActive && pos.rescueDipLevel && price < pos.rescueDipLevel) return;
		let spend = rescueRemaining * [
			.5,
			.2,
			.3,
			.4,
			.9
		][Math.min(count, 5) - 1];
		spend = Math.min(spend, rescueRemaining, bal(bot, lane).free);
		spend = Math.floor(spend * 100) / 100;
		if (spend < 5) {
			bot.online = false;
			bot.lastSeen = now;
			replies.push({
				tone: "alert",
				mono: true,
				text: `BOT SHUTDOWN – POSITION KEPT\n${pair}\nRescue #${count} needs at least 5 ${lane} but the wallet can pay ${spend.toFixed(2)}. Buy was not sent.`
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
			text: `RESCUE TRADE #${count} done on ${pair}\nLoss was ${pct.toFixed(2)}%\nBought $${spend.toFixed(2)} ${lane} @ ${pxFmt(price)}\nNew avg entry: ${pxFmt(newAvg)}\nRescue pool left: $${(st.rescuePool - pos.rescueUsed).toFixed(2)}`
		});
		return;
	}
	if (price <= pos.trailingStop || price <= pos.stopLoss) closePosition(bot, lane, price, price <= pos.stopLoss ? "STOP-LOSS SELL" : "TRAILING-STOP SELL", now, replies);
}
function manageIsaac(bot, now, replies) {
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
		isaac.cooldownUntil = now + 3e4;
		bot.history.push({
			ts: now,
			type: "isaac_profit",
			amount: profit,
			invested: cost,
			profitPct: profit / cost * 100,
			orderInfo: `Orders: ${n}`,
			lane: "ISAAC"
		});
		laneOf(bot, "USDT").allocated = Math.max(100, laneOf(bot, "USDT").allocated + profit);
		replies.push({
			tone: "trade",
			mono: true,
			text: `ISAAC DCA TP Success (+${isaacDynamicTp(n)}%)\nSold ${total.toFixed(4)} ${base} @ ${pxFmt(price)}\nPnL +$${profit.toFixed(2)}\nCycle reset to 0/7. Profit swept into the main USDT pool.`
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
		isaac.cooldownUntil = now + 3e4;
		bot.history.push({
			ts: now,
			type: "isaac_profit",
			amount: profit,
			invested: cost,
			profitPct: cost ? profit / cost * 100 : 0,
			orderInfo: `Orders: ${n}`,
			lane: "ISAAC"
		});
		replies.push({
			tone: "trade",
			mono: true,
			text: `ISAAC TRAILING STOP HIT\nSold ${total.toFixed(4)} ${base} @ ${pxFmt(price)}\nPnL ${profit >= 0 ? "+" : ""}$${profit.toFixed(2)}`
		});
		return;
	}
	if (n >= 7 && isaac.trailingStop == null) {
		isaac.trailingDistance = price * .02;
		isaac.trailingStop = price - isaac.trailingDistance;
		replies.push({
			tone: "alert",
			text: `TRAILING STOP ACTIVATED\nIsaac is 7/7. Stop ${pxFmt(isaac.trailingStop)} (2% under ${pxFmt(price)}).`
		});
		return;
	}
	if (n < 7 && replies.length === 0 && Math.random() < .18) {
		const need = isaacNextDrop(n);
		const drop = last > 0 ? (last - price) / last * 100 : 0;
		if (n === 0 || drop >= need) {
			const quote = bal(bot, "USDT").free;
			let buy = n === 0 ? 5e3 : isaac.initial * Math.pow(1.5, n);
			buy = Math.min(buy, isaac.virtualUsdt, quote);
			buy = Math.floor(buy * 100) / 100;
			if (buy >= 100) {
				const qty = buy / price;
				addFree(bot, "USDT", -buy);
				addFree(bot, base, qty);
				isaac.virtualUsdt -= buy;
				isaac.orders.push({
					entry: price,
					size: qty
				});
				isaac.cooldownUntil = now + 35e3;
				replies.push({
					tone: "trade",
					text: `ISAAC DCA #${n + 1}: Bought ${qty.toFixed(4)} ${base} @ ${pxFmt(price)} ($${buy.toFixed(2)})`
				});
			}
		}
	}
}
function tickBot(bot, now) {
	const next = structuredClone(bot);
	const replies = [];
	for (const base of Object.keys(next.prices)) {
		const anchor = next.anchors[base] || next.prices[base];
		const shock = (Math.random() - .47) * .0042;
		let px = next.prices[base] * (1 + shock);
		const band = anchor * .14;
		px = Math.min(anchor + band, Math.max(anchor * .08, Math.max(anchor - band, px)));
		next.prices[base] = px;
		if (!next.series[base]) next.series[base] = [];
		next.series[base].push(px);
		if (next.series[base].length > 80) next.series[base].shift();
	}
	managePosition(next, "USDT", now, replies);
	if (replies.length === 0) managePosition(next, "USDC", now, replies);
	if (replies.length === 0) manageIsaac(next, now, replies);
	if (replies.length === 0) for (const lane of ["USDT", "USDC"]) {
		const st = laneOf(next, lane);
		if (!st.symbol || st.position) continue;
		const price = priceOf(next, st.symbol);
		if (!price) continue;
		if (indicators(next, st.symbol, price).score >= 86 && Math.random() < .22) {
			openManaged(next, lane, price, "EMA Momentum Alignment (Elite)", now, replies);
			break;
		}
	}
	return {
		bot: next,
		replies
	};
}
function pushReplies(messages, replies, now) {
	const extra = replies.map((r) => ({
		id: uid("m"),
		from: r.tone === "service" ? "service" : "bot",
		text: r.text,
		ts: now,
		tone: r.tone,
		mono: r.mono
	}));
	const unreadAdd = extra.filter((m) => m.from === "bot").length;
	const merged = [...messages, ...extra];
	return {
		messages: merged.length > 500 ? merged.slice(-500) : merged,
		unreadAdd
	};
}
function msg(from, text, ts, extra) {
	return {
		id: uid("m"),
		from,
		text,
		ts,
		...extra
	};
}
function freshLane(allocated) {
	return {
		symbol: null,
		lastSymbol: null,
		allocated,
		rescuePool: 2e4,
		position: null
	};
}
function createBot(input) {
	const now = input.now ?? Date.now();
	const bot = {
		id: uid("bot"),
		name: input.name.trim() || "Bot",
		exchange: input.exchange,
		online: input.online ?? true,
		unread: 0,
		lastSeen: now,
		lanes: {
			USDT: freshLane(5e3),
			USDC: freshLane(5e3)
		},
		isaac: {
			symbol: "NEAR/USDT",
			orders: [],
			virtualUsdt: 36500,
			allocated: 36500,
			initial: 1e3,
			paused: false,
			trailingStop: null,
			trailingDistance: null,
			dipActive: false,
			dipLevel: null,
			dipDistance: null,
			cooldownUntil: now + 6e4
		},
		wallet: {
			USDT: {
				free: 15e3,
				locked: 0
			},
			USDC: {
				free: 8e3,
				locked: 0
			}
		},
		history: [],
		conversation: null,
		prices: {},
		anchors: {},
		series: {},
		messages: [],
		inbox: [],
		typing: false,
		entryCooldownUntil: now + 25e3
	};
	for (const base of BASES) ensureBase(bot, base);
	bot.messages.push(msg("service", `${bot.name} is online on ${bot.exchange}. USDT uses /pair. USDC uses /pair2. Isaac watches NEAR/USDT.`, now, { tone: "service" }));
	return bot;
}
function seedBots(now = Date.now()) {
	const testnet = createBot({
		name: "ABinance Testnet",
		exchange: "Binance Testnet",
		now: now - 108e5
	});
	testnet.lanes.USDT.symbol = "ETH/USDT";
	testnet.lanes.USDT.lastSymbol = "ETH/USDT";
	testnet.lanes.USDT.allocated = 6840;
	testnet.prices.ETH = 3266;
	testnet.anchors.ETH = 3210;
	ensureBase(testnet, "ETH", 3210);
	testnet.series.ETH.push(3266);
	const ethPos = makePosition(3210, 1.42, "EMA Momentum Alignment (Elite)");
	ethPos.trailingDistance = 156.768;
	ethPos.trailingStop = 3266 - ethPos.trailingDistance;
	ethPos.phase = 0;
	testnet.lanes.USDT.position = ethPos;
	testnet.wallet.ETH = {
		free: 1.42,
		locked: 0
	};
	testnet.wallet.USDT = {
		free: 18420.55,
		locked: 80
	};
	testnet.wallet.USDC = {
		free: 9100,
		locked: 0
	};
	testnet.wallet.NEAR = {
		free: 1297.48,
		locked: 0
	};
	testnet.isaac.orders = [{
		entry: 5.05,
		size: 990.1
	}, {
		entry: 4.88,
		size: 307.38
	}];
	testnet.isaac.virtualUsdt = 3e4;
	testnet.isaac.cooldownUntil = now + 2e4;
	testnet.prices.NEAR = 4.82;
	testnet.history = [
		{
			ts: now - 936e5,
			type: "main_profit",
			amount: 214.4,
			invested: 3100,
			profitPct: 6.92,
			lane: "USDT"
		},
		{
			ts: now - 324e5,
			type: "isaac_profit",
			amount: 162.15,
			invested: 4200,
			profitPct: 3.86,
			orderInfo: "Orders: 3",
			lane: "ISAAC"
		},
		{
			ts: now - 18e6,
			type: "main_profit",
			amount: 88.2,
			invested: 2500,
			profitPct: 3.53,
			lane: "USDT"
		}
	];
	const t0 = now - 84e5;
	testnet.messages = [
		msg("service", "ABinance Testnet connected. Lanes USDT and USDC. Isaac on NEAR/USDT.", t0, { tone: "service" }),
		msg("me", "/pair", t0 + 2e4),
		msg("bot", "Enter trading pair (e.g., BTC/USDT)", t0 + 21e3),
		msg("me", "ETH/USDT", t0 + 4e4),
		msg("bot", "ETH/USDT pair added", t0 + 41e3),
		msg("me", "/buy_price ETH/USDT 3210 1.42", t0 + 8e4),
		msg("bot", `Position initialized for ETH/USDT: 1.42000000 ETH at entry price $3210.00\nPrimary $${pxFmt(ethPos.primary)}, Secondary $${pxFmt(ethPos.secondary)}, Stop-Loss $${pxFmt(ethPos.stopLoss)}, Trailing Stop $${pxFmt(ethPos.trailingStop)}`, t0 + 82e3, {
			tone: "trade",
			mono: true
		}),
		msg("me", "/price", now - 36e4),
		msg("bot", "ETH/USDT: $3266.00", now - 36e4 + 800)
	];
	testnet.entryCooldownUntil = now + 12e3;
	const live = createBot({
		name: "ABinance Live",
		exchange: "Binance",
		now: now - 72e5
	});
	live.lanes.USDT.symbol = "BTC/USDT";
	live.lanes.USDT.lastSymbol = "BTC/USDT";
	live.lanes.USDT.allocated = 5e3;
	live.wallet.USDT = {
		free: 24210,
		locked: 0
	};
	live.wallet.USDC = {
		free: 4e3,
		locked: 0
	};
	live.isaac.cooldownUntil = now + 9e4;
	live.messages = [
		msg("service", "ABinance Live is online. No position yet. BTC/USDT is the active pair.", now - 72e5, { tone: "service" }),
		msg("me", "/pair BTC/USDT", now - 72e5 + 4e3),
		msg("bot", "BTC/USDT pair added", now - 72e5 + 5e3)
	];
	const bybit = createBot({
		name: "Bybit Spot",
		exchange: "Bybit",
		now: now - 3e6
	});
	bybit.lanes.USDT.symbol = "SOL/USDT";
	bybit.lanes.USDT.lastSymbol = "SOL/USDT";
	bybit.lanes.USDT.allocated = 5420;
	bybit.prices.SOL = 151.4;
	const sol = makePosition(146.2, 18.4, "VWAP Reclaim Orderflow Flip");
	sol.phase = 1;
	sol.trailingDistance = 1.2112;
	sol.trailingStop = 151.4 - sol.trailingDistance;
	bybit.lanes.USDT.position = sol;
	bybit.wallet.SOL = {
		free: 18.4,
		locked: 0
	};
	bybit.wallet.USDT = {
		free: 8600,
		locked: 0
	};
	bybit.messages = [msg("service", "Bybit Spot online. SOL/USDT is in BREATHE.", now - 24e5, { tone: "service" }), msg("bot", fmtTg("BREATHE  +3.56%", [
		"Pair          SOL/USDT",
		"Unrealized    +3.56%",
		"Trail         0.80%",
		`Stop          ${pxFmt(sol.trailingStop)}`,
		"Locked        ≈ +2.70%",
		"Pattern       VWAP Reclaim Orderflow Flip",
		"Goal          Profit locked. Distance is SACRED."
	]), now - 24e4, {
		tone: "trade",
		mono: true
	})];
	bybit.unread = 1;
	const bitget = createBot({
		name: "Bitget Spot",
		exchange: "Bitget",
		online: false,
		now: now - 288e5
	});
	bitget.lanes.USDT.symbol = "XRP/USDT";
	bitget.lanes.USDT.lastSymbol = "XRP/USDT";
	bitget.wallet.USDT = {
		free: 6300,
		locked: 0
	};
	bitget.wallet.XRP = {
		free: 1200,
		locked: 0
	};
	bitget.lastSeen = now - 21e5;
	bitget.messages.push(msg("service", "Bitget Spot is offline. Messages you send stay queued.", now - 21e5, { tone: "service" }));
	return [
		testnet,
		live,
		bybit,
		bitget
	];
}
function previewLine(bot) {
	if (bot.typing) return "typing...";
	const last = [...bot.messages].reverse().find((m) => m.from !== "service") ?? bot.messages[bot.messages.length - 1];
	if (!last) return bot.online ? "online" : "offline";
	return ((last.from === "me" ? "You: " : "") + last.text).replace(/\s+/g, " ").slice(0, 86);
}
function laneQuotes(bot) {
	const out = [];
	for (const lane of ["USDT", "USDC"]) {
		const st = bot.lanes[lane];
		if (!st.symbol) continue;
		const price = priceOf(bot, st.symbol);
		if (!price) continue;
		const pnl = st.position ? (price - st.position.entry) / st.position.entry * 100 : null;
		out.push({
			pair: st.symbol,
			price,
			pnl
		});
	}
	return out;
}
var draining = /* @__PURE__ */ new Set();
function sleep(ms) {
	return new Promise((r) => setTimeout(r, ms));
}
var audioCtx = null;
function playTone(important) {
	try {
		const Ctx = window.AudioContext || window.webkitAudioContext;
		audioCtx = audioCtx || new Ctx();
		audioCtx.resume();
		const o = audioCtx.createOscillator();
		const g = audioCtx.createGain();
		o.type = "sine";
		const t = audioCtx.currentTime;
		o.frequency.setValueAtTime(important ? 740 : 880, t);
		o.frequency.exponentialRampToValueAtTime(important ? 440 : 620, t + .09);
		g.gain.setValueAtTime(1e-4, t);
		g.gain.exponentialRampToValueAtTime(.04, t + .02);
		g.gain.exponentialRampToValueAtTime(1e-4, t + .16);
		o.connect(g);
		g.connect(audioCtx.destination);
		o.start(t);
		o.stop(t + .18);
	} catch {}
}
function soundFor(replies, active, sound) {
	if (!sound || !replies.length) return;
	if (replies.some((r) => r.tone === "trade" || r.tone === "alert")) playTone(true);
	else if (!active && replies.some((r) => r.tone === "normal")) playTone(false);
}
var seeded = seedBots();
var useDesk = create()(persist((set, get) => ({
	bots: seeded,
	activeId: seeded[0]?.id ?? "",
	sound: true,
	infoOpen: false,
	query: "",
	setQuery: (query) => set({ query }),
	setActive: (id) => set((s) => ({
		activeId: id,
		bots: s.bots.map((b) => b.id === id ? {
			...b,
			unread: 0
		} : b)
	})),
	toggleSound: () => set((s) => ({ sound: !s.sound })),
	toggleInfo: () => set((s) => ({ infoOpen: !s.infoOpen })),
	toggleOnline: (id) => {
		const bot = get().bots.find((b) => b.id === id);
		if (!bot) return;
		const online = !bot.online;
		set((s) => ({ bots: s.bots.map((b) => b.id === id ? {
			...b,
			online,
			lastSeen: Date.now(),
			typing: false,
			messages: online ? [...b.messages, {
				id: uid("m"),
				from: "service",
				text: "Bot is online.",
				ts: Date.now(),
				tone: "service"
			}] : b.messages
		} : b) }));
		if (online) get().drain(id);
	},
	addBot: (name, exchange) => {
		const bot = createBot({
			name,
			exchange,
			online: true
		});
		set((s) => ({
			bots: [...s.bots, bot],
			activeId: bot.id
		}));
	},
	removeBot: (id) => set((s) => {
		const bots = s.bots.filter((b) => b.id !== id);
		return {
			bots,
			activeId: s.activeId === id ? bots[0]?.id ?? "" : s.activeId
		};
	}),
	send: (text) => {
		const trimmed = text.trim();
		if (!trimmed) return;
		const id = get().activeId;
		const bot = get().bots.find((b) => b.id === id);
		if (!bot) return;
		const jobId = uid("j");
		const mine = {
			id: jobId,
			from: "me",
			text: trimmed,
			ts: Date.now(),
			pending: !bot.online
		};
		const notice = !bot.online && !bot.messages.some((m) => m.pending) ? [{
			id: uid("m"),
			from: "service",
			text: "Bot is offline. This message will send when it is back.",
			ts: Date.now(),
			tone: "service"
		}] : [];
		set((s) => ({ bots: s.bots.map((b) => b.id === id ? {
			...b,
			messages: [
				...b.messages,
				mine,
				...notice
			],
			inbox: [...b.inbox, {
				id: jobId,
				text: trimmed
			}],
			unread: 0
		} : b) }));
		if (bot.online) get().drain(id);
	},
	tickAll: () => {
		const activeId = get().activeId;
		const sound = get().sound;
		let played = false;
		set((s) => ({ bots: s.bots.map((b) => {
			if (!b.online || b.typing || b.inbox.length) return b;
			const { bot, replies } = tickBot(b, Date.now());
			if (!replies.length) return {
				...bot,
				messages: b.messages,
				inbox: b.inbox,
				typing: false,
				unread: b.unread
			};
			const pushed = pushReplies(b.messages, replies, Date.now());
			const active = b.id === activeId;
			if (!played) {
				soundFor(replies, active, sound);
				played = replies.some((r) => r.tone === "trade" || r.tone === "alert" || !active);
			}
			return {
				...bot,
				messages: pushed.messages,
				inbox: b.inbox,
				typing: false,
				unread: active ? 0 : b.unread + pushed.unreadAdd
			};
		}) }));
	},
	drain: async (id) => {
		if (draining.has(id)) return;
		draining.add(id);
		try {
			for (;;) {
				const bot = get().bots.find((b) => b.id === id);
				if (!bot || bot.inbox.length === 0) break;
				if (!bot.online) break;
				const job = bot.inbox[0];
				set((s) => ({ bots: s.bots.map((b) => b.id === id ? {
					...b,
					typing: true
				} : b) }));
				await sleep(/^\/(status|compound_status|isaac_status)/.test(job.text) ? 720 : 480);
				const cur = get().bots.find((b) => b.id === id);
				if (!cur || cur.inbox[0]?.id !== job.id) {
					set((s) => ({ bots: s.bots.map((b) => b.id === id ? {
						...b,
						typing: false
					} : b) }));
					continue;
				}
				if (!cur.online) {
					set((s) => ({ bots: s.bots.map((b) => b.id === id ? {
						...b,
						typing: false,
						messages: b.messages.map((m) => m.id === job.id ? {
							...m,
							pending: true
						} : m)
					} : b) }));
					break;
				}
				const applied = applyUserText(cur, job.text, Date.now());
				const pushed = pushReplies(cur.messages.map((m) => m.id === job.id ? {
					...m,
					pending: false
				} : m), applied.replies, Date.now());
				const active = get().activeId === id;
				set((s) => ({ bots: s.bots.map((b) => b.id !== id ? b : {
					...applied.bot,
					messages: pushed.messages,
					inbox: b.inbox.filter((j) => j.id !== job.id),
					typing: false,
					unread: active ? 0 : b.unread + (active ? 0 : pushed.unreadAdd)
				}) }));
				soundFor(applied.replies, active, get().sound);
			}
		} finally {
			draining.delete(id);
			const bot = get().bots.find((b) => b.id === id);
			if (bot && bot.online && bot.inbox.length) get().drain(id);
		}
	}
}), {
	name: "wire-desk-v1",
	partialize: (s) => ({
		bots: s.bots.map((b) => ({
			...b,
			typing: false,
			inbox: b.online ? [] : b.inbox
		})),
		activeId: s.activeId,
		sound: s.sound,
		infoOpen: s.infoOpen
	})
}));
function initials(name) {
	const parts = name.split(/\s+/).filter(Boolean);
	return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}
function hm(ts) {
	return new Date(ts).toLocaleTimeString([], {
		hour: "2-digit",
		minute: "2-digit"
	});
}
function dayLabel(ts) {
	const d = new Date(ts);
	const now = /* @__PURE__ */ new Date();
	const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
	const diff = Math.round((start(now) - start(d)) / 864e5);
	if (diff === 0) return "Today";
	if (diff === 1) return "Yesterday";
	return d.toLocaleDateString([], {
		day: "numeric",
		month: "short",
		year: "numeric"
	});
}
function Rich({ text }) {
	const lines = text.split("\n");
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(import_jsx_runtime.Fragment, { children: lines.map((line, i) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { children: [i > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("br", {}), line.split(/(\*\*[^*]+\*\*)/g).map((part, j) => part.startsWith("**") && part.endsWith("**") ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("strong", {
		className: "font-semibold",
		children: part.slice(2, -2)
	}, j) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: part }, j))] }, i)) });
}
function Avatar({ name, online, size = "md" }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
		className: `relative grid ${size === "sm" ? "size-9 text-xs" : "size-12 text-sm"} shrink-0 place-items-center rounded-full bg-accent-strong font-semibold text-fg`,
		children: [initials(name), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: `absolute right-0 bottom-0 size-2.5 rounded-full ring-2 ring-sidebar ${online ? "bg-online" : "bg-subtle"}` })]
	});
}
function Desk() {
	const bots = useDesk((s) => s.bots);
	const activeId = useDesk((s) => s.activeId);
	const sound = useDesk((s) => s.sound);
	const infoOpen = useDesk((s) => s.infoOpen);
	const query = useDesk((s) => s.query);
	const setQuery = useDesk((s) => s.setQuery);
	const setActive = useDesk((s) => s.setActive);
	const toggleSound = useDesk((s) => s.toggleSound);
	const toggleInfo = useDesk((s) => s.toggleInfo);
	const [listMode, setListMode] = (0, import_react.useState)(true);
	const [adding, setAdding] = (0, import_react.useState)(false);
	const active = bots.find((b) => b.id === activeId) ?? null;
	(0, import_react.useEffect)(() => {
		const id = window.setInterval(() => useDesk.getState().tickAll(), 2500);
		return () => window.clearInterval(id);
	}, []);
	(0, import_react.useEffect)(() => {
		const onKey = (e) => {
			if (!e.altKey || e.key < "1" || e.key > "9") return;
			const bot = useDesk.getState().bots[Number(e.key) - 1];
			if (!bot) return;
			e.preventDefault();
			setActive(bot.id);
			setListMode(false);
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [setActive]);
	const shown = (0, import_react.useMemo)(() => {
		const q = query.trim().toLowerCase();
		if (!q) return bots;
		return bots.filter((b) => {
			return `${b.name} ${b.exchange} ${previewLine(b)}`.toLowerCase().includes(q);
		});
	}, [bots, query]);
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "flex h-dvh min-h-0 overflow-hidden bg-bg text-fg",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("aside", {
				className: `${listMode ? "flex" : "hidden"} min-h-0 w-full shrink-0 flex-col border-r border-line bg-sidebar md:flex md:w-80`,
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex items-center justify-between px-4 pt-4 pb-2",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h1", {
							className: "text-lg font-semibold tracking-tight",
							children: "Wire"
						}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-xs text-muted",
							children: "Private desk"
						})] }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							onClick: () => setAdding(true),
							className: "grid size-10 place-items-center rounded-full bg-elevated text-accent hover:bg-bubble-out",
							"aria-label": "Add a bot",
							children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Plus, { className: "size-5" })
						})]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
						className: "px-3 pb-2",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
							className: "flex items-center gap-2 rounded-full bg-bg px-3 py-2 text-sm text-muted",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Search, { className: "size-4 shrink-0" }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								value: query,
								onChange: (e) => setQuery(e.target.value),
								placeholder: "Search",
								className: "w-full bg-transparent text-fg outline-none placeholder:text-subtle"
							})]
						})
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "min-h-0 flex-1 overflow-y-auto",
						children: [shown.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "px-4 py-6 text-sm text-muted",
							children: "No bots match that search."
						}), shown.map((bot) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ChatRow, {
							bot,
							active: bot.id === activeId,
							onPick: () => {
								setActive(bot.id);
								setListMode(false);
							}
						}, bot.id))]
					})
				]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("section", {
				className: `${listMode ? "hidden" : "flex"} min-h-0 min-w-0 flex-1 flex-col md:flex`,
				children: active ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Thread, {
					bot: active,
					sound,
					onBack: () => setListMode(true),
					onToggleSound: toggleSound,
					onToggleInfo: toggleInfo
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
					className: "grid flex-1 place-items-center px-6 text-center",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-lg font-medium",
							children: "No bot selected"
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "mt-1 text-sm text-muted",
							children: "Add one to start a private chat."
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							onClick: () => setAdding(true),
							className: "mt-4 rounded-full bg-accent-strong px-4 py-2 text-sm font-medium text-fg",
							children: "Add a bot"
						})
					] })
				})
			}),
			active && infoOpen && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
				type: "button",
				className: "fixed inset-0 z-20 bg-bg/70 xl:hidden",
				"aria-label": "Close details",
				onClick: toggleInfo
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(InfoPanel, {
				bot: active,
				onClose: toggleInfo
			})] }),
			adding && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(AddBotDialog, { onClose: () => setAdding(false) })
		]
	});
}
function ChatRow({ bot, active, onPick }) {
	const last = bot.messages[bot.messages.length - 1];
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("button", {
		type: "button",
		onClick: onPick,
		className: `flex w-full items-center gap-3 px-3 py-2.5 text-left ${active ? "bg-bubble-out" : "hover:bg-elevated"}`,
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Avatar, {
			name: bot.name,
			online: bot.online
		}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
			className: "min-w-0 flex-1",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
				className: "flex items-baseline justify-between gap-2",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
					className: "truncate font-medium",
					children: bot.name
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
					className: "shrink-0 text-xs text-muted",
					children: last ? hm(last.ts) : ""
				})]
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
				className: "mt-0.5 flex items-center justify-between gap-2",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
					className: `truncate text-sm ${bot.typing ? "text-accent" : "text-muted"}`,
					children: previewLine(bot)
				}), bot.unread > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
					className: "grid min-w-5 place-items-center rounded-full bg-accent px-1.5 text-xs font-semibold text-bg",
					children: bot.unread
				})]
			})]
		})]
	});
}
function Thread({ bot, sound, onBack, onToggleSound, onToggleInfo }) {
	const scroller = (0, import_react.useRef)(null);
	const [chatQuery, setChatQuery] = (0, import_react.useState)("");
	const [searchOpen, setSearchOpen] = (0, import_react.useState)(false);
	const quotes = laneQuotes(bot);
	const visible = chatQuery.trim() ? bot.messages.filter((m) => m.text.toLowerCase().includes(chatQuery.trim().toLowerCase())) : bot.messages;
	const lastLive = [...bot.messages].reverse().find((m) => m.from === "bot");
	(0, import_react.useLayoutEffect)(() => {
		const el = scroller.current;
		if (!el || chatQuery.trim()) return;
		const go = () => {
			el.scrollTop = el.scrollHeight;
		};
		go();
		const id = requestAnimationFrame(go);
		return () => cancelAnimationFrame(id);
	}, [
		bot.id,
		bot.messages.length,
		bot.typing,
		chatQuery
	]);
	(0, import_react.useEffect)(() => {
		setChatQuery("");
		setSearchOpen(false);
	}, [bot.id]);
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [
		/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("header", {
			className: "flex shrink-0 items-center gap-2 border-b border-line bg-sidebar px-2 py-2 md:px-3",
			children: [
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: onBack,
					className: "grid size-10 place-items-center rounded-full text-muted hover:bg-elevated md:hidden",
					"aria-label": "Back to bots",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ChevronLeft, { className: "size-5" })
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Avatar, {
					name: bot.name,
					online: bot.online,
					size: "sm"
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "min-w-0 flex-1",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
						className: "truncate font-semibold leading-tight",
						children: bot.name
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: `truncate text-xs ${bot.online ? "text-online" : "text-muted"}`,
						children: [bot.typing ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
							className: "text-accent",
							children: "typing"
						}) : bot.online ? "online" : `last seen ${hm(bot.lastSeen)}`, /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
							className: "text-subtle",
							children: [" · ", bot.exchange]
						})]
					})]
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
					className: "hidden text-right sm:block",
					children: quotes.map((q) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "font-mono text-xs leading-4 tabular-nums text-muted",
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
								className: "text-fg",
								children: q.pair
							}),
							" ",
							pxFmt(q.price),
							q.pnl != null && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
								className: q.pnl >= 0 ? "text-online" : "text-danger",
								children: [
									" ",
									q.pnl >= 0 ? "+" : "",
									q.pnl.toFixed(2),
									"%"
								]
							})
						]
					}, q.pair))
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: () => setSearchOpen((v) => !v),
					className: "grid size-10 place-items-center rounded-full text-muted hover:bg-elevated",
					"aria-label": "Search this chat",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Search, { className: "size-5" })
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: onToggleSound,
					className: "grid size-10 place-items-center rounded-full text-muted hover:bg-elevated",
					"aria-label": sound ? "Mute notifications" : "Unmute notifications",
					children: sound ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Volume2, { className: "size-5" }) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(VolumeX, { className: "size-5" })
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: onToggleInfo,
					className: "grid size-10 place-items-center rounded-full text-muted hover:bg-elevated",
					"aria-label": "Bot details",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(PanelRight, { className: "size-5" })
				})
			]
		}),
		searchOpen && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
			className: "shrink-0 border-b border-line bg-sidebar px-3 py-2",
			children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
				autoFocus: true,
				value: chatQuery,
				onChange: (e) => setChatQuery(e.target.value),
				placeholder: "Search in this chat",
				className: "w-full rounded-full bg-bg px-3 py-2 text-sm outline-none"
			})
		}),
		/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			ref: scroller,
			className: "min-h-0 flex-1 overflow-y-auto px-3 py-3 md:px-6",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "mx-auto flex max-w-3xl flex-col gap-1.5",
				children: [visible.map((m, i) => {
					const prev = visible[i - 1];
					const showDay = !prev || new Date(prev.ts).toDateString() !== new Date(m.ts).toDateString();
					return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [showDay && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
						className: "my-2 flex justify-center",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
							className: "rounded-full bg-bubble-in px-3 py-1 text-xs text-muted",
							children: dayLabel(m.ts)
						})
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Bubble, { message: m })] }, m.id);
				}), bot.typing && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "msg-in mr-auto flex items-center gap-1 rounded-md rounded-bl-sm bg-bubble-in px-3 py-3",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: "typing-dot size-1.5 rounded-full bg-muted" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: "typing-dot size-1.5 rounded-full bg-muted" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: "typing-dot size-1.5 rounded-full bg-muted" })
					]
				})]
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "sr-only",
				"aria-live": "polite",
				children: lastLive?.text ?? ""
			})]
		}),
		/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Composer, { bot })
	] });
}
function Bubble({ message }) {
	if (message.from === "service") return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: "my-1 flex justify-center",
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
			className: "max-w-md rounded-full bg-bubble-in px-3 py-1 text-center text-xs text-muted",
			children: message.text
		})
	});
	const mine = message.from === "me";
	const edge = message.tone === "trade" ? "tone-trade" : message.tone === "alert" ? "tone-alert" : "";
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: `msg-in flex ${mine ? "justify-end" : "justify-start"}`,
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: `bubble-col rounded-lg px-3 py-1.5 text-sm leading-normal ${mine ? "rounded-br-sm bg-bubble-out" : `rounded-bl-sm bg-bubble-in ${edge}`} ${message.mono ? "font-mono text-xs leading-relaxed" : ""}`,
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
				className: "float-right mt-1 ml-3 inline-flex items-center gap-1 text-xs text-subtle",
				children: [
					message.pending && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Clock, {
						className: "size-3",
						"aria-label": "Waiting to send"
					}),
					hm(message.ts),
					mine && !message.pending && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Check, {
						className: "size-3 text-accent",
						"aria-label": "Sent"
					})
				]
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Rich, { text: message.text })]
		})
	});
}
function Composer({ bot }) {
	const send = useDesk((s) => s.send);
	const [draft, setDraft] = (0, import_react.useState)("");
	const [menuIndex, setMenuIndex] = (0, import_react.useState)(0);
	const inputRef = (0, import_react.useRef)(null);
	(0, import_react.useEffect)(() => {
		setDraft("");
		setMenuIndex(0);
		inputRef.current?.focus();
	}, [bot.id]);
	const waiting = bot.conversation?.kind === "pair" ? `Waiting for a ${bot.conversation.lane} pair. /cancel to abort.` : bot.conversation?.kind === "buy_price" ? "Waiting for pair, price, and amount. /cancel to abort." : bot.conversation?.kind === "mb" ? `Waiting for the ${bot.conversation.lane} amount. /cancel to abort.` : null;
	const menuOpen = draft.startsWith("/") && !draft.includes(" ") && !draft.includes("\n");
	const matches = (0, import_react.useMemo)(() => {
		if (!menuOpen) return [];
		const needle = draft.toLowerCase();
		return COMMANDS.filter((c) => needle === "/" || c.name.startsWith(needle) || c.hint.toLowerCase().includes(needle.slice(1)));
	}, [draft, menuOpen]);
	(0, import_react.useEffect)(() => {
		setMenuIndex(0);
	}, [draft]);
	function submit(text) {
		const value = text.trim();
		if (!value) return;
		send(value);
		setDraft("");
	}
	function onKeyDown(e) {
		if (menuOpen && matches.length) {
			if (e.key === "ArrowDown") {
				e.preventDefault();
				setMenuIndex((i) => (i + 1) % matches.length);
				return;
			}
			if (e.key === "ArrowUp") {
				e.preventDefault();
				setMenuIndex((i) => (i - 1 + matches.length) % matches.length);
				return;
			}
			if (e.key === "Escape") {
				e.preventDefault();
				setDraft("");
				return;
			}
		}
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			if (menuOpen && matches.length && !draft.includes(" ")) {
				submit(matches[Math.min(menuIndex, matches.length - 1)]?.name ?? draft);
				return;
			}
			submit(draft);
		}
	}
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "relative shrink-0 border-t border-line bg-sidebar",
		children: [
			menuOpen && matches.length > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
				className: "absolute right-2 bottom-full left-2 z-10 mb-2 max-h-72 overflow-y-auto rounded-md border border-line bg-sidebar py-1 shadow-lg",
				children: matches.map((cmd, i) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("button", {
					type: "button",
					onMouseEnter: () => setMenuIndex(i),
					onClick: () => submit(cmd.name),
					className: `flex w-full items-baseline gap-3 px-3 py-2 text-left ${i === menuIndex ? "bg-elevated" : ""}`,
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
						className: `w-36 shrink-0 font-medium ${cmd.danger ? "text-danger" : "text-accent"}`,
						children: cmd.name
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
						className: "truncate text-sm text-muted",
						children: cmd.hint
					})]
				}) }, cmd.name))
			}),
			waiting && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "px-4 pt-2 text-xs text-accent",
				children: waiting
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)(CommandRail, { onSend: (name) => {
				submit(name);
				inputRef.current?.focus();
			} }),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "flex items-end gap-2 px-3 pt-1 pb-3",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("textarea", {
					ref: inputRef,
					rows: 1,
					value: draft,
					onChange: (e) => setDraft(e.target.value),
					onKeyDown,
					placeholder: "Write a message",
					className: "max-h-32 min-h-11 flex-1 resize-none rounded-md bg-bg px-3 py-2.5 text-sm outline-none placeholder:text-subtle"
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: () => submit(draft),
					disabled: !draft.trim(),
					className: "grid size-11 shrink-0 place-items-center rounded-full bg-accent-strong text-fg disabled:bg-elevated disabled:text-subtle",
					"aria-label": "Send",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Send, { className: "size-5" })
				})]
			})
		]
	});
}
function CommandRail({ onSend }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: "flex gap-3 overflow-x-auto px-3 pt-2 pb-1",
		children: [
			"USDT",
			"USDC",
			"Isaac",
			"Session"
		].map((group) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: "flex shrink-0 items-center gap-1",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
				className: "pr-1 text-xs font-semibold tracking-wide text-subtle uppercase",
				children: group
			}), COMMANDS.filter((c) => c.group === group).map((cmd) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)(CommandChip, {
				cmd,
				onSend
			}, cmd.name))]
		}, group))
	});
}
function CommandChip({ cmd, onSend }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
		type: "button",
		onClick: () => onSend(cmd.name),
		title: cmd.hint,
		className: `shrink-0 rounded-full bg-bg px-2.5 py-1.5 text-xs font-medium ${cmd.danger ? "text-danger" : "text-accent"} hover:bg-elevated`,
		children: cmd.name
	});
}
function InfoPanel({ bot, onClose }) {
	const toggleOnline = useDesk((s) => s.toggleOnline);
	const removeBot = useDesk((s) => s.removeBot);
	const [confirm, setConfirm] = (0, import_react.useState)(false);
	const usdt = bot.lanes.USDT;
	const usdc = bot.lanes.USDC;
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("aside", {
		className: "absolute inset-y-0 right-0 z-30 flex w-full min-h-0 flex-col border-l border-line bg-sidebar sm:w-80 xl:static",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: "flex items-center justify-between px-4 py-3",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
				className: "font-semibold",
				children: "Details"
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
				type: "button",
				onClick: onClose,
				className: "grid size-10 place-items-center rounded-full hover:bg-elevated",
				"aria-label": "Close details",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(X, { className: "size-5" })
			})]
		}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: "min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-6",
			children: [
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "flex items-center gap-3",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Avatar, {
						name: bot.name,
						online: bot.online
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
						className: "font-medium",
						children: bot.name
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
						className: "text-sm text-muted",
						children: bot.exchange
					})] })]
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: () => toggleOnline(bot.id),
					className: `w-full rounded-md px-3 py-2.5 text-sm font-medium ${bot.online ? "bg-elevated text-fg" : "bg-accent-strong text-fg"}`,
					children: bot.online ? "Stop bot" : "Bring online"
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)(LaneBlock, {
					title: "USDT lane",
					symbol: usdt.symbol,
					position: usdt.position,
					allocated: usdt.allocated,
					quote: bot.wallet.USDT
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)(LaneBlock, {
					title: "USDC lane",
					symbol: usdc.symbol,
					position: usdc.position,
					allocated: usdc.allocated,
					quote: bot.wallet.USDC
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "rounded-md bg-bg p-3 text-sm",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
							className: "font-medium",
							children: "Isaac DCA"
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
							className: "mt-1 text-muted",
							children: [
								bot.isaac.symbol,
								" · ",
								bot.isaac.orders.length,
								"/7 orders · ",
								bot.isaac.paused ? "paused" : "running"
							]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
							className: "font-mono text-xs text-subtle tabular-nums",
							children: [
								"Pool $",
								bot.isaac.virtualUsdt.toFixed(0),
								" / ",
								bot.isaac.allocated.toFixed(0)
							]
						})
					]
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "text-xs leading-relaxed text-subtle",
					children: "Commands stay pinned above the message box. Alt+1 to Alt+9 switches bots. This desk speaks the same command set as the trading scripts."
				}),
				!confirm ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					onClick: () => setConfirm(true),
					className: "text-sm text-danger",
					children: "Remove this bot"
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "flex gap-2",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						onClick: () => removeBot(bot.id),
						className: "rounded-md bg-danger px-3 py-2 text-sm font-medium text-fg",
						children: "Remove"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						onClick: () => setConfirm(false),
						className: "rounded-md bg-elevated px-3 py-2 text-sm",
						children: "Keep"
					})]
				})
			]
		})]
	});
}
function LaneBlock({ title, symbol, position, allocated, quote }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
		className: "rounded-md bg-bg p-3 text-sm",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
				className: "font-medium",
				children: title
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "mt-1 text-muted",
				children: symbol ?? "No pair set"
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "font-mono text-xs text-subtle tabular-nums",
				children: [
					"Allocated $",
					allocated.toFixed(0),
					" · Free $",
					quote?.free.toFixed(2) ?? "0.00"
				]
			}),
			position && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "mt-1 font-mono text-xs tabular-nums text-fg",
				children: [
					position.amount.toFixed(4),
					" @ ",
					pxFmt(position.entry),
					" · rescue ",
					position.rescueCount,
					"/5 · ",
					[
						"RUN",
						"BREATHE",
						"LOCK",
						"STEEL",
						"HARVEST",
						"MOONSHOT"
					][position.phase]
				]
			})
		]
	});
}
function AddBotDialog({ onClose }) {
	const addBot = useDesk((s) => s.addBot);
	const [name, setName] = (0, import_react.useState)("");
	const [exchange, setExchange] = (0, import_react.useState)("Binance Testnet");
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: "fixed inset-0 z-40 grid place-items-center bg-bg/70 px-4",
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
			className: "w-full max-w-md rounded-lg bg-sidebar p-5",
			onSubmit: (e) => {
				e.preventDefault();
				if (!name.trim()) return;
				addBot(name.trim(), exchange);
				onClose();
			},
			children: [
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
					className: "text-lg font-semibold",
					children: "Add a bot"
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "mt-1 text-sm text-muted",
					children: "Each bot keeps its own pairs, wallet, and Isaac cycle."
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
					className: "mt-4 block text-xs font-medium text-muted",
					children: ["Name", /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
						autoFocus: true,
						value: name,
						onChange: (e) => setName(e.target.value),
						placeholder: "ABinance Testnet",
						className: "mt-1 w-full rounded-md bg-bg px-3 py-2.5 text-sm text-fg outline-none"
					})]
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
					className: "mt-3 block text-xs font-medium text-muted",
					children: ["Exchange", /* @__PURE__ */ (0, import_jsx_runtime.jsx)("select", {
						value: exchange,
						onChange: (e) => setExchange(e.target.value),
						className: "mt-1 w-full rounded-md bg-bg px-3 py-2.5 text-sm text-fg outline-none",
						children: [
							"Binance Testnet",
							"Binance",
							"Bybit",
							"Bitget"
						].map((o) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", { children: o }, o))
					})]
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "mt-5 flex justify-end gap-2",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						onClick: onClose,
						className: "rounded-md px-3 py-2 text-sm text-muted",
						children: "Cancel"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "submit",
						className: "rounded-md bg-accent-strong px-4 py-2 text-sm font-medium text-fg",
						children: "Create"
					})]
				})
			]
		})
	});
}
function Home() {
	const [ready, setReady] = (0, import_react.useState)(false);
	(0, import_react.useEffect)(() => {
		const api = useDesk.persist;
		if (api.hasHydrated()) setReady(true);
		return api.onFinishHydration(() => setReady(true));
	}, []);
	if (!ready) return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", { className: "h-dvh bg-bg" });
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Desk, {});
}
//#endregion
export { Home as component };
