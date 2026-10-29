/* WIRE Companion v2 — Telegram-style control app for iPhone.
   iOS 15.8-safe vanilla JS: no build step, no frameworks, no optional
   APIs beyond ES2019. Talks to the relay: live stream + remote commands. */
(function () {
  "use strict";

  /* ------------------------------------------------------------ themes -- */
  var THEMES = {
    "real-black": { name: "Real Black", vars: ["#000000", "#060709", "#101216", "#0d0f13", "#1d9bf0", "#8b5cf6", "#1d9bf0", "#a78bfa", "#eef0f3", "#9aa3ad", "#69737e", "#1d2128"] },
    onyx: { name: "Onyx", vars: ["#04060b", "#090d15", "#131a26", "#10151f", "#3b82f6", "#06b6d4", "#5ea2ff", "#22d3ee", "#f2f5fa", "#9aa8bd", "#66748c", "#1d2534"] },
    midnight: { name: "Midnight", vars: ["#050d1a", "#0a1526", "#152338", "#111f33", "#2e90fa", "#8b5cf6", "#58a6ff", "#a78bfa", "#f0f5fc", "#9db0c8", "#64778f", "#1e3148"] },
    "deep-blue": { name: "Deep Blue", vars: ["#030c18", "#071426", "#0f2340", "#0c1e37", "#0ea5e9", "#6366f1", "#38bdf8", "#818cf8", "#ecf5fe", "#93aecb", "#5f7d9c", "#16304f"] },
    "royal-blue": { name: "Royal Blue", vars: ["#060a20", "#0c1233", "#181f52", "#141b46", "#6366f1", "#a855f7", "#818cf8", "#c084fc", "#eef0ff", "#a3abd8", "#6f78ad", "#232c5e"] },
    aurora: { name: "Aurora", vars: ["#04110e", "#081b16", "#0f2b24", "#0c2620", "#14b8a6", "#818cf8", "#2dd4bf", "#67e8f9", "#eafff8", "#96c4b8", "#5f9184", "#17392f"] },
    graphite: { name: "Graphite", vars: ["#0b0c0f", "#121317", "#1d2026", "#181b21", "#475569", "#818cf8", "#93c5fd", "#a5b4fc", "#f4f6f9", "#a8afbb", "#747c89", "#272b33"] },
    emerald: { name: "Emerald", vars: ["#03110a", "#06190f", "#0c2b1c", "#0a2418", "#10b981", "#4ade80", "#34d399", "#a3e635", "#eafff4", "#9cc5ae", "#63937b", "#143527"] },
    amethyst: { name: "Amethyst", vars: ["#0a0616", "#120b24", "#1e1440", "#191236", "#8b5cf6", "#d946ef", "#a78bfa", "#e879f9", "#f5f2ff", "#b0a6d9", "#7d72ab", "#291d52"] },
    "rose-noir": { name: "Rose Noir", vars: ["#12060c", "#1d0a13", "#301223", "#281020", "#db2777", "#f472b6", "#fb7185", "#f0abfc", "#fff2f6", "#d3a3b4", "#9c7284", "#3f1a30"] },
    neon: { name: "Neon Pulse", vars: ["#050510", "#0a0a1a", "#14142c", "#101024", "#22d3ee", "#e879f9", "#22d3ee", "#f0abfc", "#f2f2ff", "#9d9dc0", "#6a6a94", "#202046"] },
    sunset: { name: "Sunset", vars: ["#120809", "#1d0d0e", "#31171a", "#291316", "#f97316", "#ec4899", "#fb923c", "#f472b6", "#fff4ef", "#d4a8a0", "#a17872", "#432026"] }
  };
  var TEXT_SIZES = [["0.875rem", "Small"], ["0.95rem", "Default"], ["1.05rem", "Large"], ["1.15rem", "XL"]];

  function applyTheme(id) {
    var theme = THEMES[id] || THEMES["real-black"];
    var root = document.documentElement;
    var keys = ["--bg", "--sidebar", "--elevated", "--bubble-in", "--bubble-out-a", "--bubble-out-b", "--accent", "--accent-2", "--fg", "--muted", "--subtle", "--line"];
    for (var i = 0; i < keys.length; i++) root.style.setProperty(keys[i], theme.vars[i]);
    root.style.setProperty("--online", id === "neon" ? "#00ffa3" : "#00d97e");
    root.style.setProperty("--danger", id === "neon" ? "#ff3860" : "#ff4d67");
    root.style.setProperty("--warn", id === "neon" ? "#ffd23f" : "#ffb224");
    root.style.setProperty("--accent-grad", "linear-gradient(135deg, var(--accent), var(--accent-2))");
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme.vars[0]);
  }

  /* ------------------------------------------------------------ state -- */
  var LS = { key: "wc-key", theme: "wc-theme", size: "wc-text-size", ahs: "wc-ahs-hide" };
  function lsGet(k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } }
  function lsSet(k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (e) {} }

  var state = {
    key: lsGet(LS.key),
    ws: null,
    wsState: "off", // off | connecting | live | error
    devices: 0,
    bots: [],            // [{id,name,exchange,online,photo,pins,commands}]
    msgs: {},            // botId -> [{id,from,text,ts,tone,mono,buttons,via,local}]
    unread: {},          // botId -> count
    active: null,        // botId
    atBottom: true,
    stick: true,
    reconnectDelay: 1000,
    reconnectTimer: null,
    menuOpen: false,
    menuForced: false,
    lastRendered: {}     // botId -> last ts+count for list previews
  };

  function bot(id) {
    for (var i = 0; i < state.bots.length; i++) if (state.bots[i].id === id) return state.bots[i];
    return null;
  }
  function activeBot() { return state.active ? bot(state.active) : null; }
  function msgs(id) { if (!state.msgs[id]) state.msgs[id] = []; return state.msgs[id]; }

  /* ------------------------------------------------------------ utils -- */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function hm(ts) {
    var d = new Date(ts);
    return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
  }
  function dayKey(ts) {
    var d = new Date(ts);
    return d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate();
  }
  function dayLabel(ts) {
    var d = new Date(ts), now = new Date();
    var start = function (x) { return new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime(); };
    var diff = Math.round((start(now) - start(d)) / 86400000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
  }
  function initials(name) {
    var parts = String(name || "?").split(/\s+/);
    var s = ((parts[0] || "?").charAt(0) + (parts[1] ? parts[1].charAt(0) : "")).toUpperCase();
    return s || "?";
  }
  function isCmd(text) { return /^\/[a-zA-Z0-9_]{1,50}(\s|$)/.test(String(text || "").trim()); }
  function previewText(m) {
    var t = String(m && m.text || "").replace(/\s+/g, " ");
    return t.length > 60 ? t.slice(0, 60) + "…" : t;
  }
  function toast(text) {
    var el = document.getElementById("toast");
    el.textContent = text;
    el.classList.add("has");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.remove("has"); }, 2200);
  }

  var app = document.getElementById("app");

  /* ----------------------------------------------------------- render -- */
  function avatarHtml(b, dot) {
    var inner = b && b.photo
      ? '<img src="' + esc(b.photo) + '" alt="" />'
      : esc(initials(b && b.name));
    var st = dot ? '<span class="st' + (b && b.online ? " on" : "") + '"></span>' : "";
    return '<span class="avatar">' + inner + st + "</span>";
  }

  function statusPillHtml() {
    var map = { live: ["is-live", state.devices > 0 ? "Live · " + state.devices + " device" + (state.devices > 1 ? "s" : "") : "Live · waiting"], connecting: ["is-connecting", "Connecting…"], error: ["is-error", "Connection error"], off: ["", "Offline"] };
    var m = map[state.wsState] || map.off;
    return '<span class="pill ' + m[0] + '"><span class="dot"></span><span>' + esc(m[1]) + "</span></span>";
  }

  function renderPair(message) {
    app.innerHTML =
      '<div class="screen is-visible">' +
        '<div class="pair">' +
          '<div class="logo">W</div>' +
          "<h1>WIRE Companion</h1>" +
          "<p>" + esc(message || "Enter the pairing key from your PC — open WIRE Settings → Companion sync on the desktop app. Every chat streams here live, and you can send commands from anywhere.") + "</p>" +
          '<input id="pairkey" inputmode="latin" autocapitalize="characters" autocomplete="off" spellcheck="false" placeholder="WIRE-XXXX-XXXX" maxlength="24" />' +
          '<button class="go" id="pairgo" data-act="pair">Connect</button>' +
          '<div class="hint">The key lives only in WIRE on your PC.<br />No account, no cloud storage — just your relay.</div>' +
        "</div>" +
        '<div class="toast" id="toast"></div>' +
      "</div>";
    var input = document.getElementById("pairkey");
    input.value = state.key;
    input.addEventListener("input", function () { this.value = this.value.toUpperCase().replace(/[^A-Z0-9-]/g, "").slice(0, 24); });
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") doPair(); });
    if (!message) input.focus();
  }

  function doPair() {
    var input = document.getElementById("pairkey");
    var key = (input ? input.value : state.key).toUpperCase().replace(/[^A-Z0-9-]/g, "");
    if (key.replace(/[^A-Z0-9]/g, "").length < 6) { toast("The key looks too short — check WIRE Settings on your PC."); return; }
    state.key = key;
    lsSet(LS.key, key);
    connect();
  }

  function renderList() {
    var rows = "";
    var bots = state.bots;
    if (!bots.length) {
      rows = '<div class="empty">Waiting for your PC…<br /><br />Open <b>WIRE</b> on the computer, go to <b>Settings → Companion sync</b>, enable it with this pairing key, and your chats will appear here.</div>';
    }
    for (var i = 0; i < bots.length; i++) {
      var b = bots[i];
      var list = msgs(b.id);
      var last = list.length ? list[list.length - 1] : null;
      var unread = state.unread[b.id] || 0;
      rows +=
        '<button class="row" data-act="open" data-id="' + esc(b.id) + '">' +
          '<span class="av">' + avatarHtml(b, true) + "</span>" +
          '<span class="mid">' +
            '<span class="l1"><span class="name">' + esc(b.name) + '</span><span class="time">' + (last ? hm(last.ts) : "") + "</span></span>" +
            '<span class="l2"><span class="prev' + (unread ? " unread" : "") + '">' + (b.online || b.id === "botmother" ? "" : "") + esc(previewText(last)) + "</span>" +
            (unread ? '<span class="badge">' + (unread > 99 ? "99+" : unread) + "</span>" : "") +
          "</span>" +
        "</span>" +
        "</button>";
    }
    app.innerHTML =
      '<div class="screen is-visible">' +
        '<div class="topbar">' +
          '<div class="brand"><span class="mark">W</span><span><span class="t">WIRE</span><br /><span class="s">Companion</span></span></div>' +
          '<div style="display:flex;align-items:center;gap:8px;">' + statusPillHtml() +
          '<button class="iconbtn" data-act="settings" aria-label="Settings">⚙︎</button></div>' +
        "</div>" +
        '<div class="ahs' + (lsGet(LS.ahs) ? "" : " has") + '" id="ahs">' +
          "<div>Like a real app: tap <b>Share</b> (□↑) then <b>“Add to Home Screen”</b>.</div>" +
          '<button class="x" data-act="ahs-hide">✕</button>' +
        "</div>" +
        '<div class="chatlist">' + rows + "</div>" +
      "</div>";
  }

  function cmdMenuHtml(botObj) {
    var cmds = (botObj && botObj.commands) || [];
    if (!cmds.length) return "";
    var items = "";
    for (var i = 0; i < cmds.length; i++) {
      items += '<li><button data-act="cmd" data-cmd="' + esc(cmds[i].name) + '">' +
        '<span class="cname' + (cmds[i].danger ? " danger" : "") + '">' + esc(cmds[i].name) + "</span>" +
        '<span class="chint">' + esc(cmds[i].hint || "") + "</span></button></li>";
    }
    return '<div class="cmdmenu' + (state.menuOpen ? " has" : "") + '" id="cmdmenu"><div class="head"><span>Bot commands</span><span>' + cmds.length + "</span></div><ul>" + items + "</ul></div>";
  }

  function renderChat() {
    var b = activeBot();
    if (!b) { state.active = null; renderList(); return; }
    app.innerHTML =
      '<div class="screen is-visible" id="chatscreen">' +
        '<div class="chathead">' +
          '<button class="back" data-act="back">‹</button>' +
          '<span class="av">' + avatarHtml(b, true) + "</span>" +
          '<span class="mid"><span class="name">' + esc(b.name) + '</span><br /><span class="stat' + (b.online || b.id === "botmother" ? " on" : "") + '" id="chatstat">' + esc(b.id === "botmother" ? "bot manager — always here" : b.online ? "online" : "offline") + ' · ' + esc(b.exchange || "") + "</span></span>" +
          '<button class="iconbtn" data-act="settings" aria-label="Settings">⚙︎</button>' +
        "</div>" +
        '<div class="pinbar" id="pinbar"></div>' +
        '<div class="thread" id="thread"><div class="wrap" id="wrap"></div>' +
          '<button class="jump" id="jump" data-act="jump">↓</button>' +
        "</div>" +
        '<div class="composer">' +
          '<textarea id="draft" rows="1" placeholder="Message" enterkeyhint="send"></textarea>' +
          '<button class="menu-btn' + (state.menuForced ? " open" : "") + '" id="menubtn" data-act="menu">Menu</button>' +
          '<button class="send" id="sendbtn" data-act="send">➤</button>' +
          cmdMenuHtml(b) +
        "</div>" +
      "</div>" +
      '<div class="toast" id="toast"></div>';
    renderPins();
    rebuildThread();
    wireChat();
  }

  function renderPins() {
    var b = activeBot();
    var bar = document.getElementById("pinbar");
    if (!b || !bar) return;
    var list = msgs(b.id);
    var pins = (b.pins || []).map(function (id) {
      for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
      return null;
    }).filter(Boolean);
    if (!pins.length) { bar.className = "pinbar"; bar.innerHTML = ""; return; }
    var idx = Math.min(bar._idx || 0, pins.length - 1);
    bar._idx = idx;
    var p = pins[idx];
    bar.className = "pinbar has";
    bar.innerHTML =
      '<span class="bar"></span>' +
      '<span class="mid"><span class="t">Pinned' + (pins.length > 1 ? " · " + (idx + 1) + "/" + pins.length : "") + '</span><span class="x">' + esc(previewText(p)) + "</span></span>" +
      (pins.length > 1 ? '<button class="un" data-act="pin-prev">▲</button><button class="un" data-act="pin-next">▼</button>' : "") +
      '<button class="un" data-act="pin-remove" data-id="' + esc(p.id) + '" aria-label="Unpin">✕</button>';
    bar._pins = pins;
  }

  function bubbleHtml(m, b, tail, grouped) {
    var mine = m.from === "me";
    var cmd = mine && isCmd(m.text);
    var left = !mine || cmd; /* Telegram bot style: commands on the LEFT */
    var cls = "bubble " + (left ? "in" : "out") + (tail ? " tail" : "") + (cmd && mine ? " cmd" : "") +
      (m.tone === "alert" && !mine ? " alert" : m.tone === "trade" && !mine ? " trade" : "") +
      ((b.pins || []).indexOf(m.id) >= 0 ? " pinnedmsg" : "");
    var body = richText(m.text);
    var kb = "";
    if (m.buttons && m.buttons.length) {
      kb = '<span class="kb">';
      for (var i = 0; i < m.buttons.length; i++) {
        kb += '<button data-act="btn" data-cmd="' + esc(m.buttons[i].command) + '">' + esc(m.buttons[i].label) + "</button>";
      }
      kb += "</span>";
    }
    var meta =
      '<span class="meta">' +
      (m.via === "phone" ? '<span class="ph">📱</span>' : "") +
      (m.local ? '<span class="ph">◌</span>' : "") +
      esc(hm(m.ts)) +
      (mine && !left && !m.local ? ' <span class="tick">✓✓</span>' : "") +
      "</span>";
    return (
      '<div class="msg' + (left ? "" : " mine-right") + (tail ? " tail" : "") + '" data-mid="' + esc(m.id) + '" data-ts="' + m.ts + '">' +
      (left ? '<span class="gav">' + (tail ? avatarHtml(b, false) : "") + "</span>" : "") +
      '<div class="' + cls + '" data-act="bubble" data-mid="' + esc(m.id) + '">' + body + kb + meta + "</div>" +
      "</div>"
    );
  }

  function richText(text) {
    var lines = String(text || "").split("\n");
    var out = "";
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (i) out += "<br />";
      var parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
      for (var j = 0; j < parts.length; j++) {
        var part = parts[j];
        if (!part) continue;
        if (part.charAt(0) === "*" && part.charAt(1) === "*" && part.charAt(part.length - 1) === "*" && part.charAt(part.length - 2) === "*") {
          out += "<b>" + esc(part.slice(2, -2)) + "</b>";
        } else if (part.charAt(0) === "*" && part.charAt(part.length - 1) === "*" && part.length > 2) {
          out += "<i>" + esc(part.slice(1, -1)) + "</i>";
        } else if (/^\/[a-zA-Z0-9_]{1,50}(\s|$)/.test(part)) {
          var sp = part.indexOf(" ");
          var token = sp < 0 ? part : part.slice(0, sp);
          var rest = sp < 0 ? "" : part.slice(sp);
          out += '<button class="chip" data-act="cmd" data-cmd="' + esc(token) + '">' + esc(token) + "</button>" + esc(rest);
        } else {
          out += esc(part);
        }
      }
    }
    return out;
  }

  function rebuildThread() {
    var wrap = document.getElementById("wrap");
    var b = activeBot();
    if (!wrap || !b) return;
    var list = msgs(b.id);
    var html = "";
    var lastDay = "";
    for (var i = 0; i < list.length; i++) {
      var m = list[i];
      var day = dayKey(m.ts);
      if (day !== lastDay) { html += '<div class="daysep"><span>' + esc(dayLabel(m.ts)) + "</span></div>"; lastDay = day; }
      var next = list[i + 1];
      var prevSame = i > 0 && list[i - 1].from === m.from && m.ts - list[i - 1].ts < 300000;
      var nextSame = next && next.from === m.from && next.ts - m.ts < 300000;
      html += bubbleHtml(m, b, !nextSame, prevSame);
    }
    wrap.innerHTML = html;
    scrollToBottom(false);
  }

  function appendMessage(botId, m) {
    var list = msgs(botId);
    list.push(m);
    if (list.length > 250) list.splice(0, list.length - 250);
    if (state.active === botId && document.getElementById("wrap")) {
      if (state.stick || m.from === "me") {
        var wrap = document.getElementById("wrap");
        var b = activeBot();
        var last = list[list.length - 2];
        var dayChanged = !last || dayKey(last.ts) !== dayKey(m.ts);
        var div = document.createElement("div");
        div.innerHTML = (dayChanged ? '<div class="daysep"><span>' + esc(dayLabel(m.ts)) + "</span></div>" : "") + bubbleHtml(m, b, true, last && last.from === m.from && m.ts - last.ts < 300000);
        while (div.firstChild) wrap.appendChild(div.firstChild);
        scrollToBottom(false);
        renderPins();
      } else {
        var jump = document.getElementById("jump");
        if (jump) { jump.classList.add("has"); jump._n = (jump._n || 0) + 1; jump.textContent = "↓" + (jump._n > 1 ? jump._n : ""); }
      }
    } else {
      state.unread[botId] = (state.unread[botId] || 0) + 1;
    }
    refreshRow(botId);
  }

  function refreshRow(botId) {
    if (!state.active) renderListRow(botId);
  }

  function renderListRow(botId) {
    var listEl = document.querySelector(".chatlist");
    if (!listEl) return;
    var b = bot(botId);
    if (!b) return;
    var row = listEl.querySelector('[data-id="' + botId + '"]');
    var list = msgs(botId);
    var last = list.length ? list[list.length - 1] : null;
    var unread = state.unread[botId] || 0;
    if (!row) { renderList(); return; }
    row.querySelector(".prev").textContent = previewText(last);
    row.querySelector(".prev").className = "prev" + (unread ? " unread" : "");
    row.querySelector(".time").textContent = last ? hm(last.ts) : "";
    var badge = row.querySelector(".badge");
    if (unread) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "badge";
        row.querySelector(".l2").appendChild(badge);
      }
      badge.textContent = unread > 99 ? "99+" : String(unread);
    } else if (badge) badge.remove();
  }

  function scrollToBottom(smooth) {
    var thread = document.getElementById("thread");
    if (!thread) return;
    thread.style.scrollBehavior = smooth ? "smooth" : "auto";
    thread.scrollTop = thread.scrollHeight;
    thread.style.scrollBehavior = "auto";
    state.stick = true;
    var jump = document.getElementById("jump");
    if (jump) { jump.classList.remove("has"); jump._n = 0; jump.textContent = "↓"; }
  }

  /* ------------------------------------------------------------- ws ---- */
  function connect() {
    if (!state.key) { renderPair(); return; }
    clearTimeout(state.reconnectTimer);
    var endpoint = location.origin.replace(/^http/i, "ws") + "/ws";
    var ws;
    try { ws = new WebSocket(endpoint); } catch (e) { scheduleReconnect(); return; }
    state.ws = ws;
    state.wsState = "connecting";
    updatePill();

    ws.onopen = function () {
      state.reconnectDelay = 1000;
      ws.send(JSON.stringify({ type: "hello", role: "viewer", key: state.key, name: "WIRE Companion" }));
      state.wsState = "live";
      updatePill();
    };
    ws.onmessage = function (event) {
      var data;
      try { data = JSON.parse(String(event.data)); } catch (e) { return; }
      if (!data || !data.type) return;
      if (data.type === "session") onSession(data.bots || []);
      else if (data.type === "backlog") onBacklog(data.botId, data.messages || []);
      else if (data.type === "message") onLive(data.botId, data.message);
      else if (data.type === "presence") {
        var b = bot(data.botId);
        if (b) { b.online = !!data.online; updateHeadStatus(b); refreshRow(b.id); if (!state.active) renderList(); }
      } else if (data.type === "error" && data.error === "invalid-key") {
        state.wsState = "error";
        updatePill();
        state.key = "";
        lsSet(LS.key, "");
        try { ws.close(); } catch (e) {}
        renderPair("That pairing key was rejected. Check WIRE Settings → Companion sync on your PC and try again.");
      }
    };
    ws.onclose = function () {
      if (state.ws === ws) {
        state.ws = null;
        if (state.wsState !== "error") state.wsState = "connecting";
        updatePill();
        scheduleReconnect();
      }
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }

  function scheduleReconnect() {
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(connect, state.reconnectDelay);
    state.reconnectDelay = Math.min(30000, Math.round(state.reconnectDelay * 1.7));
  }

  function updatePill() {
    var pill = document.querySelector(".pill");
    if (pill) pill.outerHTML = statusPillHtml();
  }

  function updateHeadStatus(b) {
    var el = document.getElementById("chatstat");
    if (el && state.active === b.id) {
      el.textContent = (b.id === "botmother" ? "bot manager — always here" : b.online ? "online" : "offline") + " · " + (b.exchange || "");
      el.className = "stat" + (b.online || b.id === "botmother" ? " on" : "");
    }
  }

  function onSession(bots) {
    var known = {};
    for (var i = 0; i < state.bots.length; i++) known[state.bots[i].id] = true;
    state.bots = bots;
    for (var j = 0; j < bots.length; j++) if (!known[bots[j].id]) { state.unread[bots[j].id] = state.unread[bots[j].id] || 0; }
    if (state.active && !bot(state.active)) { state.active = null; renderList(); return; }
    if (!state.active) renderList();
    else {
      var b = activeBot();
      if (b) {
        updateHeadStatus(b);
        renderPins();
        rebuildThread(); /* pins/photo/commands may have changed */
        updateMenuButton();
      }
    }
  }

  function onBacklog(botId, messages) {
    var clean = [];
    for (var i = 0; i < messages.length; i++) {
      var m = messages[i];
      if (m && typeof m.text === "string") clean.push(normMessage(m));
    }
    state.msgs[botId] = clean;
    if (state.active === botId) rebuildThread();
    else refreshRow(botId);
    if (!state.active) renderListRow(botId);
  }

  function normMessage(m) {
    return {
      id: String(m.id || Math.random().toString(36).slice(2)),
      from: m.from === "me" ? "me" : "bot",
      text: String(m.text || ""),
      ts: Number(m.ts) || Date.now(),
      tone: m.tone || "normal",
      mono: !!m.mono,
      buttons: Array.isArray(m.buttons) ? m.buttons : null,
      via: m.via === "phone" ? "phone" : null,
      local: false
    };
  }

  function onLive(botId, message) {
    if (!message || typeof message.text !== "string") return;
    var m = normMessage(message);
    /* reconcile optimistic local echo — drop it from state AND from the DOM */
    var list = msgs(botId);
    for (var i = list.length - 1; i >= 0; i--) {
      if (list[i].local && list[i].from === "me" && list[i].text === m.text) {
        var ghostId = list[i].id;
        list.splice(i, 1);
        var ghost = document.querySelector('[data-mid="' + cssEscape(ghostId) + '"]');
        var ghostMsg = ghost && ghost.closest ? ghost.closest(".msg") : null;
        if (ghostMsg) ghostMsg.remove();
        else if (ghost && ghost.parentNode) ghost.parentNode.remove();
        break;
      }
    }
    appendMessage(botId, m);
  }

  function cssEscape(s) {
    return String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function sendInput(text) {
    var b = activeBot();
    var value = String(text || "").trim();
    if (!b || !value) return;
    if (!state.ws || state.ws.readyState !== 1) { toast("Not connected — reconnecting…"); connect(); return; }
    state.ws.send(JSON.stringify({ type: "input", botId: b.id, text: value.slice(0, 2000) }));
    appendMessage(b.id, { id: "local-" + Date.now(), from: "me", text: value, ts: Date.now(), local: true, tone: "normal" });
  }

  function sendCtrl(action, msgId) {
    var b = activeBot();
    if (!b || !state.ws || state.ws.readyState !== 1) return;
    state.ws.send(JSON.stringify({ type: "ctrl", action: action, botId: b.id, msgId: msgId }));
  }

  /* ------------------------------------------------------- chat logic -- */
  function updateMenuButton() {
    var b = activeBot();
    var old = document.getElementById("cmdmenu");
    if (old) old.remove();
    if (b && state.menuOpen && (b.commands || []).length) {
      var composer = document.querySelector(".composer");
      if (composer) composer.insertAdjacentHTML("beforeend", cmdMenuHtml(b));
    }
    var btn = document.getElementById("menubtn");
    if (btn) btn.className = "menu-btn" + (state.menuForced ? " open" : "");
  }

  function openChat(id) {
    state.active = id;
    state.unread[id] = 0;
    state.menuOpen = false;
    state.menuForced = false;
    renderChat();
  }

  function closeChat() {
    state.active = null;
    state.menuOpen = false;
    state.menuForced = false;
    renderList();
  }

  function wireChat() {
    var draft = document.getElementById("draft");
    var thread = document.getElementById("thread");
    if (!draft || !thread) return;

    draft.addEventListener("input", function () {
      this.style.height = "auto";
      this.style.height = Math.min(110, this.scrollHeight) + "px";
      var v = this.value;
      if (v.charAt(0) === "/" && v.indexOf(" ") < 0) {
        state.menuOpen = true;
        filterMenu(v.toLowerCase());
      } else if (state.menuForced) {
        state.menuOpen = true;
        filterMenu(v.toLowerCase());
      }
    });
    draft.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        var v = draft.value.trim();
        if (v) { sendInput(v); draft.value = ""; draft.style.height = "auto"; closeMenu(); }
      }
    });

    thread.addEventListener("scroll", function () {
      var near = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
      state.stick = near;
      var jump = document.getElementById("jump");
      if (near && jump) { jump.classList.remove("has"); jump._n = 0; jump.textContent = "↓"; }
    });

    /* long-press action sheet */
    var pressTimer = null;
    thread.addEventListener("touchstart", function (e) {
      var bubble = e.target.closest ? e.target.closest(".bubble") : null;
      if (!bubble) return;
      var mid = bubble.getAttribute("data-mid");
      pressTimer = setTimeout(function () { showSheet(mid, bubble); }, 550);
    }, { passive: true });
    thread.addEventListener("touchmove", function () { clearTimeout(pressTimer); }, { passive: true });
    thread.addEventListener("touchend", function () { clearTimeout(pressTimer); }, { passive: true });
    thread.addEventListener("contextmenu", function (e) {
      var bubble = e.target.closest ? e.target.closest(".bubble") : null;
      if (bubble) { e.preventDefault(); showSheet(bubble.getAttribute("data-mid"), bubble); }
    });
  }

  function filterMenu(needle) {
    var b = activeBot();
    var menu = document.getElementById("cmdmenu");
    if (!menu || !b) return;
    var cmds = b.commands || [];
    var filtered = needle && needle !== "/" ? cmds.filter(function (c) { return c.name.indexOf(needle) === 0 || (c.hint || "").toLowerCase().indexOf(needle.slice(1)) >= 0; }) : cmds;
    var items = "";
    for (var i = 0; i < filtered.length; i++) {
      items += '<li><button data-act="cmd" data-cmd="' + esc(filtered[i].name) + '"><span class="cname' + (filtered[i].danger ? " danger" : "") + '">' + esc(filtered[i].name) + '</span><span class="chint">' + esc(filtered[i].hint || "") + "</span></button></li>";
    }
    menu.innerHTML = '<div class="head"><span>Bot commands</span><span>' + filtered.length + "</span></div>" + (items ? "<ul>" + items + "</ul>" : '<div class="empty" style="padding:18px;">No matching command</div>');
    menu.className = "cmdmenu has";
  }

  function closeMenu() {
    state.menuOpen = false;
    state.menuForced = false;
    updateMenuButton();
  }

  /* ------------------------------------------------------ action sheet -- */
  function showSheet(mid, bubbleEl) {
    var b = activeBot();
    if (!b || !mid) return;
    var m = null;
    var list = msgs(b.id);
    for (var i = 0; i < list.length; i++) if (list[i].id === mid) m = list[i];
    if (!m) return;
    var pinned = (b.pins || []).indexOf(mid) >= 0;
    var back = document.createElement("div");
    back.className = "sheet-back has";
    back.id = "sheetback";
    var sheet = document.createElement("div");
    sheet.className = "sheet has";
    sheet.id = "sheet";
    var rows = "";
    if (isCmd(m.text) && m.from === "me") rows += '<button class="accent" data-sact="rerun">▶ Run again</button>';
    rows += '<button class="accent" data-sact="' + (pinned ? "unpin" : "pin") + '">' + (pinned ? "📍 Unpin" : "📌 Pin") + "</button>";
    rows += '<button data-sact="copy">Copy text</button>';
    rows += '<button data-sact="cancel">Cancel</button>';
    sheet.innerHTML = rows;
    document.body.appendChild(back);
    document.body.appendChild(sheet);
    sheet.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-sact");
      if (!act) return;
      if (act === "rerun") sendInput(m.text);
      if (act === "pin" || act === "unpin") {
        sendCtrl("togglePin", mid);
        toast(pinned ? "Unpinning…" : "Pinning…");
      }
      if (act === "copy" && navigator.clipboard) {
        navigator.clipboard.writeText(m.text).then(function () { toast("Copied"); }, function () {});
      }
      hideSheet();
    });
    back.addEventListener("click", hideSheet);
  }

  function hideSheet() {
    var back = document.getElementById("sheetback");
    var sheet = document.getElementById("sheet");
    if (back) back.remove();
    if (sheet) sheet.remove();
  }

  /* --------------------------------------------------------- settings -- */
  function openSettings() {
    var back = document.createElement("div");
    back.className = "settings has";
    back.id = "settings";
    var theme = lsGet(LS.theme) || "real-black";
    var size = lsGet(LS.size) || "0.95rem";
    var cards = "";
    for (var id in THEMES) {
      if (!Object.prototype.hasOwnProperty.call(THEMES, id)) continue;
      var t = THEMES[id].vars;
      cards += '<button class="themecard' + (id === theme ? " sel" : "") + '" data-theme="' + id + '">' +
        '<span class="sw"><i style="background:' + t[0] + '"></i><i style="background:' + t[2] + '"></i><i class="g" style="background:linear-gradient(135deg,' + t[4] + "," + t[5] + ')"></i></span>' +
        '<span class="nm">' + esc(THEMES[id].name) + "</span></button>";
    }
    var sizes = "";
    for (var s = 0; s < TEXT_SIZES.length; s++) {
      sizes += '<button data-size="' + TEXT_SIZES[s][0] + '" class="' + (TEXT_SIZES[s][0] === size ? "sel" : "") + '">' + TEXT_SIZES[s][1] + "</button>";
    }
    back.innerHTML =
      '<div class="panel">' +
        '<div class="head"><span class="t">Settings</span><button class="iconbtn" id="setclose">✕</button></div>' +
        '<div class="body">' +
          "<h4>Theme</h4>" +
          '<div class="themegrid">' + cards + "</div>" +
          "<h4>Message text size</h4>" +
          '<div class="sizes">' + sizes + "</div>" +
          "<h4>Connection</h4>" +
          '<div class="note">Pairing key: <b>' + esc(state.key ? state.key.slice(0, 9) + "…" : "—") + "</b><br />This phone links to one PC through your relay. Commands you send run on the PC exactly like typing at the desk.</div>" +
          '<button class="rowbtn" id="setreconnect">↻ Reconnect now</button>' +
          '<button class="rowbtn danger" id="setdisconnect">Disconnect this phone</button>' +
          "<h4>About</h4>" +
          '<div class="note">WIRE Companion v2 · pairs with WIRE 1.0.9<br />Add to Home Screen for the full-screen app icon. Works on iOS 15+.</div>' +
        "</div>" +
      "</div>";
    document.body.appendChild(back);
    back.addEventListener("click", function (e) {
      var t = e.target;
      var theme = t.getAttribute && t.getAttribute("data-theme");
      if (theme) {
        lsSet(LS.theme, theme);
        applyTheme(theme);
        var cards2 = back.querySelectorAll(".themecard");
        for (var i = 0; i < cards2.length; i++) cards2[i].className = "themecard" + (cards2[i].getAttribute("data-theme") === theme ? " sel" : "");
        return;
      }
      var size = t.getAttribute && t.getAttribute("data-size");
      if (size) {
        lsSet(LS.size, size);
        document.documentElement.style.setProperty("--chat-text-size", size);
        var sizes2 = back.querySelectorAll(".sizes button");
        for (var j = 0; j < sizes2.length; j++) sizes2[j].className = sizes2[j].getAttribute("data-size") === size ? "sel" : "";
        rebuildThread();
        return;
      }
      if (t.id === "setclose" || t.id === "settings") { back.remove(); return; }
      if (t.id === "setreconnect") {
        back.remove();
        if (state.ws) { try { state.ws.close(); } catch (err) {} }
        state.reconnectDelay = 500;
        connect();
        return;
      }
      if (t.id === "setdisconnect") {
        state.key = "";
        lsSet(LS.key, "");
        if (state.ws) { try { state.ws.onclose = null; state.ws.close(); } catch (err) {} }
        state.ws = null;
        state.wsState = "off";
        back.remove();
        closeChat();
        renderPair("Disconnected. Enter a pairing key to connect again.");
      }
    });
  }

  /* -------------------------------------------------- global handlers -- */
  document.addEventListener("click", function (e) {
    var t = e.target;
    var host = t.closest ? t.closest("[data-act]") : null;
    if (!host) return;
    var action = host.getAttribute("data-act");
    if (action === "pair") doPair();
    else if (action === "open") openChat(host.getAttribute("data-id"));
    else if (action === "back") closeChat();
    else if (action === "settings") openSettings();
    else if (action === "ahs-hide") { lsSet(LS.ahs, "1"); var ahs = document.getElementById("ahs"); if (ahs) ahs.className = "ahs"; }
    else if (action === "jump") scrollToBottom(true);
    else if (action === "send") {
      var draft = document.getElementById("draft");
      if (draft && draft.value.trim()) { sendInput(draft.value.trim()); draft.value = ""; draft.style.height = "auto"; closeMenu(); }
    } else if (action === "menu") {
      var b = activeBot();
      if (!b || !(b.commands || []).length) { toast("This bot has no commands yet — edit them in the PC's Details panel."); return; }
      state.menuForced = !state.menuForced;
      state.menuOpen = state.menuForced;
      if (state.menuOpen) filterMenu(document.getElementById("draft").value.toLowerCase());
      else closeMenu();
      var btn = document.getElementById("menubtn");
      if (btn) btn.className = "menu-btn" + (state.menuForced ? " open" : "");
    } else if (action === "cmd") {
      var cmd = host.getAttribute("data-cmd");
      sendInput(cmd);
      closeMenu();
      var d = document.getElementById("draft");
      if (d) { d.value = ""; d.style.height = "auto"; }
    } else if (action === "btn") {
      sendInput(host.getAttribute("data-cmd"));
      closeMenu();
    } else if (action === "pin-remove") {
      sendCtrl("togglePin", host.getAttribute("data-id"));
      toast("Unpinning…");
    } else if (action === "pin-prev" || action === "pin-next") {
      var bar = document.getElementById("pinbar");
      if (bar && bar._pins && bar._pins.length) {
        var n = bar._pins.length;
        bar._idx = ((bar._idx || 0) + (action === "pin-next" ? 1 : -1) + n) % n;
        renderPins();
      }
    } else if (action === "bubble") {
      if (state.menuOpen) closeMenu();
    }
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && (!state.ws || state.ws.readyState > 1) && state.key) {
      state.reconnectDelay = 500;
      connect();
    }
  });
  window.addEventListener("resize", function () {
    if (state.stick) scrollToBottom(false);
  });

  /* -------------------------------------------------------------- boot -- */
  var urlKey = "";
  try {
    var params = new URLSearchParams(location.search);
    urlKey = (params.get("key") || "").toUpperCase().replace(/[^A-Z0-9-]/g, "");
  } catch (e) {}
  if (urlKey) {
    state.key = urlKey;
    lsSet(LS.key, urlKey);
    try {
      history.replaceState(null, "", location.pathname + "?source=pwa");
    } catch (e) {}
  }
  var savedTheme = lsGet(LS.theme) || "real-black";
  applyTheme(savedTheme);
  var savedSize = lsGet(LS.size);
  if (savedSize) document.documentElement.style.setProperty("--chat-text-size", savedSize);

  if (state.key) connect();
  else renderPair();
})();
