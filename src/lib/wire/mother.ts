import { createBot, uid, type Bot, type CommandSpec, type Exchange, type Message } from "@/lib/wire/engine";

export const MOTHER_ID = "botmother";

export const MOTHER_COMMANDS: CommandSpec[] = [
  { name: "/start", hint: "What BotMother can do", group: "Session" },
  { name: "/newbot", hint: "Create a trading, forwarding, or custom bot", group: "Session" },
  { name: "/newchannel", hint: "Create a channel", group: "Session" },
  { name: "/mybots", hint: "List bots and channels", group: "Session" },
  { name: "/setname", hint: "Rename a bot or channel", group: "Session" },
  { name: "/setdescription", hint: "Set the description", group: "Session" },
  { name: "/setabouttext", hint: "Set the short about text", group: "Session" },
  { name: "/setphoto", hint: "Set a profile photo", group: "Session" },
  { name: "/setcommands", hint: "Edit a bot command menu", group: "Session" },
  { name: "/token", hint: "Show a bot token", group: "Session" },
  { name: "/revoke", hint: "Replace a bot token", group: "Session" },
  { name: "/deletebot", hint: "Remove a bot or channel", group: "Session", danger: true },
  { name: "/cancel", hint: "Stop the current action", group: "Session" },
  { name: "/help", hint: "Show these commands again", group: "Session" },
];

const FOLDERS: { name: string; exchange: Exchange; directory: string }[] = [
  { name: "ABinanceTradingBot", exchange: "Binance Testnet", directory: "ABINANCE TESTNET" },
  { name: "Binance Live Bot", exchange: "Binance", directory: "BINANCE LIVE" },
  { name: "Bitget Live Bot", exchange: "Bitget", directory: "Bitget Live Bot" },
  { name: "Bybit Live Bot", exchange: "Bybit", directory: "Bybit Live Bot" },
  { name: "GROK TESTNET", exchange: "Binance Testnet", directory: "GROK TESTNET" },
  { name: "ZZZBinance METRICS LIVE", exchange: "Binance", directory: "ZZZBinance METRICS LIVE" },
];

const HELP = [
  "I am BotMother. I create and manage bots and channels in Wire, the same way BotFather does in Telegram.",
  "",
  "/newbot — trading bot, forwarding bot, or any custom bot",
  "/newchannel — create a channel",
  "/mybots — list bots and channels",
  "/setname — rename",
  "/setdescription — long description",
  "/setabouttext — short about line",
  "/setphoto — profile photo",
  "/setcommands — command menu",
  "/token — show the local token",
  "/revoke — replace the token",
  "/deletebot — remove a chat",
  "/cancel — stop the current step",
].join("\n");

export function makeMother(now = Date.now()): Bot {
  const bot = createBot({
    name: "BotMother",
    exchange: "Wire",
    online: true,
    now,
    source: "system",
    commands: MOTHER_COMMANDS,
  });
  bot.id = MOTHER_ID;
  bot.kind = "mother";
  bot.pins = [];
  bot.motherStep = null;
  bot.messages = [line("bot", HELP, now)];
  return bot;
}

export function isMother(bot: Bot): boolean {
  return bot.id === MOTHER_ID || bot.source === "system";
}

function trading(bots: Bot[]): Bot[] {
  return bots.filter((b) => !isMother(b));
}

function line(from: Message["from"], text: string, ts = Date.now()): Message {
  return { id: uid("m"), from, text, ts };
}

function say(bot: Bot, text: string, extra?: Partial<Bot>): Bot {
  return { ...bot, ...extra, typing: false, unread: 0, messages: [...bot.messages, line("bot", text)].slice(-500) };
}

function hear(bot: Bot, text: string): Bot {
  return { ...bot, messages: [...bot.messages, line("me", text)].slice(-500), unread: 0 };
}

function roster(bots: Bot[]): string {
  const list = trading(bots);
  if (!list.length) return "You have no chats yet. Send /newbot or /newchannel.";
  return list
    .map((b, i) => {
      const tag = b.kind === "channel" ? "channel" : b.kind === "forwarder" ? "forwarding bot" : b.kind === "custom" ? "custom bot" : "trading bot";
      return `${i + 1}. ${b.name} — ${tag}${b.online ? " · online" : " · offline"}`;
    })
    .join("\n");
}

function byNumber(bots: Bot[], text: string): Bot | undefined {
  const n = Number(text.trim());
  const list = trading(bots);
  if (!Number.isInteger(n) || n < 1 || n > list.length) return undefined;
  return list[n - 1];
}

function parseCommands(raw: string): CommandSpec[] {
  return raw
    .split("\n")
    .map((row) => row.trim())
    .filter(Boolean)
    .map((row) => {
      const [rawName, ...desc] = row.split("|");
      const name = rawName.trim();
      return {
        name: name.startsWith("/") ? name : `/${name}`,
        hint: desc.join("|").trim() || "Custom command",
        group: "Session" as const,
        danger: /sell|reset|emergency|buy|withdraw|delete/i.test(name),
      };
    })
    .filter((command) => /^\/[a-zA-Z0-9_]{1,50}$/.test(command.name));
}

function guessExchange(directory: string): Exchange {
  const d = directory.toLowerCase();
  if (d.includes("bitget")) return "Bitget";
  if (d.includes("bybit")) return "Bybit";
  if (d.includes("testnet") || d.includes("grok")) return "Binance Testnet";
  return "Binance";
}

function blankTradingBot(name: string, directory: string, exchange: Exchange): Bot {
  const bot = createBot({ name, exchange, online: false, source: "bridge" });
  bot.bridgeDirectory = directory;
  bot.kind = "trading";
  bot.token = uid("tok");
  bot.wallet = {};
  bot.history = [];
  bot.prices = {};
  bot.anchors = {};
  bot.series = {};
  bot.messages = [line("service", `${name} is ready. Open this chat and use the Menu button.`)];
  bot.inbox = [];
  bot.typing = false;
  bot.unread = 0;
  bot.pins = [];
  bot.lanes.USDT = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
  bot.lanes.USDC = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
  bot.isaac = { ...bot.isaac, symbol: "", orders: [], virtualUsdt: 0, allocated: 0, initial: 0, trailingStop: null, trailingDistance: null, dipActive: false, dipLevel: null, dipDistance: null };
  return bot;
}

function blankCustom(name: string, kind: "custom" | "forwarder"): Bot {
  const bot = createBot({
    name,
    exchange: "Wire",
    online: true,
    source: "custom",
    commands: [
      { name: "/start", hint: "What this bot does", group: "Session" },
      { name: "/help", hint: "List commands", group: "Session" },
    ],
  });
  bot.kind = kind;
  bot.token = uid("tok");
  bot.pins = [];
  bot.inbox = [];
  bot.messages = [line("bot", kind === "forwarder" ? `${name} is ready. Messages you send here are forwarded.` : `${name} is ready. Use Menu, or send /help.`)];
  return bot;
}

function blankChannel(name: string, about: string): Bot {
  const bot = createBot({ name, exchange: "Wire", online: true, source: "channel", commands: [] });
  bot.kind = "channel";
  bot.about = about;
  bot.description = about;
  bot.pins = [];
  bot.inbox = [];
  bot.messages = [line("service", about ? `${name}\n${about}` : `${name} was created. Write the first post.`)];
  return bot;
}

async function pickImage(): Promise<string | null> {
  if (window.wire?.selectWallpaper) {
    const picked = await window.wire.selectWallpaper();
    return picked && picked.length > 1_800_000 ? "too-big" : picked;
  }
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return resolve(null);
      if (file.size > 1_400_000) return resolve("too-big");
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : null);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(file);
    };
    input.click();
  });
}

export async function applyMother(bots: Bot[], text: string): Promise<{ bots: Bot[] }> {
  const index = bots.findIndex(isMother);
  if (index < 0) return { bots };
  let mother = hear(bots[index], text);
  let next = bots.map((b, i) => (i === index ? mother : b));
  const raw = text.trim();
  const cmd = raw.split(/\s+/)[0].toLowerCase();

  const commit = (updated: Bot, rest = next) => {
    mother = updated;
    next = rest.map((b) => (isMother(b) ? updated : b));
  };

  if (cmd === "/cancel") {
    commit(say(mother, "Cancelled. Send /help to see the command list.", { motherStep: null, motherTarget: undefined, motherDraft: undefined }));
    return { bots: next };
  }
  if (cmd === "/start" || cmd === "/help") {
    commit(say(mother, HELP, { motherStep: null, motherTarget: undefined, motherDraft: undefined }));
    return { bots: next };
  }
  if (cmd === "/mybots") {
    commit(say(mother, roster(next), { motherStep: null }));
    return { bots: next };
  }
  if (cmd === "/newbot") {
    commit(
      say(
        mother,
        "Alright, a new bot. How are we going to call it?\n\nSend the display name. I will then ask what kind of bot it is.",
        { motherStep: "newbot-name", motherTarget: undefined, motherDraft: undefined },
      ),
    );
    return { bots: next };
  }
  if (cmd === "/newchannel") {
    commit(say(mother, "A new channel. What is its name?", { motherStep: "channel-name", motherTarget: undefined, motherDraft: undefined }));
    return { bots: next };
  }
  if (cmd === "/setname" || cmd === "/setphoto" || cmd === "/setcommands" || cmd === "/deletebot" || cmd === "/setdescription" || cmd === "/setabouttext" || cmd === "/token" || cmd === "/revoke") {
    const step =
      cmd === "/setname" ? "setname-pick"
      : cmd === "/setphoto" ? "setphoto-pick"
      : cmd === "/setcommands" ? "commands-pick"
      : cmd === "/setdescription" ? "desc-pick"
      : cmd === "/setabouttext" ? "about-pick"
      : cmd === "/token" ? "token-pick"
      : cmd === "/revoke" ? "revoke-pick"
      : "delete-pick";
    commit(say(mother, `Choose a chat. Reply with its number.\n\n${roster(next)}`, { motherStep: step, motherTarget: undefined }));
    return { bots: next };
  }

  if (mother.motherStep === "newbot-name") {
    if (!raw || raw.startsWith("/")) {
      commit(say(mother, "Send a name, or /cancel."));
      return { bots: next };
    }
    commit(say(mother, "Good. What kind of bot is this?\n\n1. Trading bot — talks to a script folder on your Desktop\n2. Forwarding bot — copies what you send into a channel\n3. Custom bot — any other bot, with its own command menu", { motherStep: "newbot-kind", motherDraft: raw }));
    return { bots: next };
  }

  if (mother.motherStep === "newbot-kind") {
    const choice = raw.trim();
    const name = mother.motherDraft || "New bot";
    if (choice === "1" || /trad/i.test(choice)) {
      const free = FOLDERS.filter((p) => !trading(next).some((b) => b.bridgeDirectory === p.directory));
      const choices = free.length ? free.map((p, i) => `${i + 1}. ${p.name} — ${p.directory}`).join("\n") : "Type a Desktop folder name, for example ABINANCE TESTNET.";
      commit(say(mother, `Trading bot. Which folder on your Desktop does it use?\n\n${choices}`, { motherStep: "newbot-folder" }));
      return { bots: next };
    }
    if (choice === "2" || /forward/i.test(choice)) {
      const channels = trading(next).filter((b) => b.kind === "channel");
      const list = channels.length ? channels.map((b, i) => `${i + 1}. ${b.name}`).join("\n") : "You have no channel yet. Send skip, then create one with /newchannel.";
      commit(say(mother, `Forwarding bot ${name}. Which channel should it post into? Send a number, or skip.\n\n${list}`, { motherStep: "forward-channel" }));
      return { bots: next };
    }
    if (choice === "3" || /custom|other/i.test(choice)) {
      const created = blankCustom(name, "custom");
      commit(say(mother, `Done. ${created.name} is a custom bot.\nToken: ${created.token}\n\nOpen it and press Menu. Use /setcommands to change that menu.`, { motherStep: null, motherDraft: undefined }), [...next, created]);
      return { bots: next };
    }
    commit(say(mother, "Reply 1, 2, or 3."));
    return { bots: next };
  }

  if (mother.motherStep === "forward-channel") {
    const name = mother.motherDraft || "Forwarder";
    const channels = trading(next).filter((b) => b.kind === "channel");
    const n = Number(raw);
    const channel = Number.isInteger(n) && n >= 1 && n <= channels.length ? channels[n - 1] : undefined;
    if (!channel && raw.toLowerCase() !== "skip") {
      commit(say(mother, "Send a channel number, or skip."));
      return { bots: next };
    }
    const created = blankCustom(name, "forwarder");
    created.linkedChannelId = channel?.id;
    commit(say(mother, `Done. ${created.name} will forward messages${channel ? ` into ${channel.name}` : ""}.\nToken: ${created.token}`, { motherStep: null, motherDraft: undefined }), [...next, created]);
    return { bots: next };
  }

  if (mother.motherStep === "channel-name") {
    if (!raw || raw.startsWith("/")) {
      commit(say(mother, "Send the channel name, or /cancel."));
      return { bots: next };
    }
    commit(say(mother, "Send a short description. Send skip if you want none.", { motherStep: "channel-about", motherDraft: raw }));
    return { bots: next };
  }

  if (mother.motherStep === "channel-about") {
    const name = mother.motherDraft || "Channel";
    const about = raw.toLowerCase() === "skip" ? "" : raw;
    const created = blankChannel(name, about);
    commit(say(mother, `Done. Channel ${created.name} is in your chat list. Open it and write a post. Posts stay on the left, like Telegram.`, { motherStep: null, motherDraft: undefined }), [...next, created]);
    return { bots: next };
  }

  if (mother.motherStep === "newbot-folder") {
    const free = FOLDERS.filter((p) => !trading(next).some((b) => b.bridgeDirectory === p.directory));
    const n = Number(raw);
    const picked = Number.isInteger(n) && n >= 1 && n <= free.length ? free[n - 1] : undefined;
    const directory = picked?.directory ?? raw;
    const name = mother.motherDraft || picked?.name || "New bot";
    if (!directory || directory.startsWith("/")) {
      commit(say(mother, "Send a folder name, or /cancel."));
      return { bots: next };
    }
    if (trading(next).some((b) => b.bridgeDirectory === directory)) {
      commit(say(mother, "That folder already has a chat. Send another folder, or /cancel."));
      return { bots: next };
    }
    const created = blankTradingBot(picked?.name && !mother.motherDraft ? picked.name : name, directory, picked?.exchange ?? guessExchange(directory));
    commit(
      say(mother, `Done. Congratulations.\n\n${created.name} is in your chat list.\nFolder: ${directory}\n\nOpen that chat and press Menu. Send /setphoto here if you want a profile picture.`, {
        motherStep: null,
        motherTarget: undefined,
        motherDraft: undefined,
      }),
      [...next, created],
    );
    return { bots: next };
  }

  const picking = ["setname-pick", "setphoto-pick", "commands-pick", "delete-pick", "desc-pick", "about-pick", "token-pick", "revoke-pick"].includes(mother.motherStep || "");
  if (picking) {
    const target = byNumber(next, raw);
    if (!target) {
      commit(say(mother, `Reply with a number from this list.\n\n${roster(next)}`));
      return { bots: next };
    }
    if (mother.motherStep === "setname-pick") {
      commit(say(mother, `Send the new name for ${target.name}.`, { motherStep: "setname-value", motherTarget: target.id }));
      return { bots: next };
    }
    if (mother.motherStep === "commands-pick") {
      commit(say(mother, `Send the Menu for ${target.name}. One command per line:\n/status | Show the book\n/pair | Set the USDT pair`, { motherStep: "commands-value", motherTarget: target.id }));
      return { bots: next };
    }
    if (mother.motherStep === "delete-pick") {
      commit(say(mother, `This removes the ${target.name} chat from Wire only. The script stays on your PC.\n\nSend YES to delete it.`, { motherStep: "delete-confirm", motherTarget: target.id }));
      return { bots: next };
    }
    if (mother.motherStep === "desc-pick") {
      commit(say(mother, `Send the description for ${target.name}.`, { motherStep: "desc-value", motherTarget: target.id }));
      return { bots: next };
    }
    if (mother.motherStep === "about-pick") {
      commit(say(mother, `Send the short about text for ${target.name}.`, { motherStep: "about-value", motherTarget: target.id }));
      return { bots: next };
    }
    if (mother.motherStep === "token-pick") {
      const token = target.token || "This trading chat uses a folder, not a token.";
      commit(say(mother, `${target.name}\n${token}`, { motherStep: null, motherTarget: undefined }));
      return { bots: next };
    }
    if (mother.motherStep === "revoke-pick") {
      if (target.kind === "trading" || target.kind === "channel") {
        commit(say(mother, "That chat has no token to replace.", { motherStep: null }));
        return { bots: next };
      }
      const token = uid("tok");
      next = next.map((b) => (b.id === target.id ? { ...b, token } : b));
      commit(say(next.find(isMother) ?? mother, `Token replaced for ${target.name}.\n${token}`, { motherStep: null, motherTarget: undefined }), next);
      return { bots: next };
    }
    const photo = await pickImage();
    if (photo === "too-big") {
      commit(say(mother, "That picture is too large. Choose one under about 1 MB.", { motherStep: null, motherTarget: undefined }));
      return { bots: next };
    }
    if (!photo) {
      commit(say(mother, "No picture selected. Send /setphoto to try again.", { motherStep: null, motherTarget: undefined }));
      return { bots: next };
    }
    next = next.map((b) => (b.id === target.id ? { ...b, photo } : b));
    commit(say(next.find(isMother) ?? mother, `Profile photo updated for ${target.name}.`, { motherStep: null, motherTarget: undefined }), next);
    return { bots: next };
  }

  if (mother.motherStep === "setname-value" && mother.motherTarget) {
    const name = raw.replace(/\s+/g, " ").slice(0, 48);
    if (!name || name.startsWith("/")) {
      commit(say(mother, "Send the new name, or /cancel."));
      return { bots: next };
    }
    next = next.map((b) => (b.id === mother.motherTarget ? { ...b, name } : b));
    commit(say(next.find(isMother) ?? mother, `Name updated. This bot is now ${name}.`, { motherStep: null, motherTarget: undefined }), next);
    return { bots: next };
  }

  if (mother.motherStep === "desc-value" && mother.motherTarget) {
    next = next.map((b) => (b.id === mother.motherTarget ? { ...b, description: raw } : b));
    commit(say(next.find(isMother) ?? mother, "Description updated.", { motherStep: null, motherTarget: undefined }), next);
    return { bots: next };
  }
  if (mother.motherStep === "about-value" && mother.motherTarget) {
    next = next.map((b) => (b.id === mother.motherTarget ? { ...b, about: raw } : b));
    commit(say(next.find(isMother) ?? mother, "About text updated.", { motherStep: null, motherTarget: undefined }), next);
    return { bots: next };
  }

  if (mother.motherStep === "commands-value" && mother.motherTarget) {
    const commands = parseCommands(raw);
    if (!commands.length) {
      commit(say(mother, "I could not read any commands. Use lines like /status | Show the book."));
      return { bots: next };
    }
    next = next.map((b) => (b.id === mother.motherTarget ? { ...b, commands } : b));
    commit(say(next.find(isMother) ?? mother, `Menu saved. ${commands.length} commands.`, { motherStep: null, motherTarget: undefined }), next);
    return { bots: next };
  }

  if (mother.motherStep === "delete-confirm" && mother.motherTarget) {
    if (raw.toUpperCase() !== "YES") {
      commit(say(mother, "Not deleted. Send YES to confirm, or /cancel."));
      return { bots: next };
    }
    const gone = next.find((b) => b.id === mother.motherTarget);
    next = next.filter((b) => b.id !== mother.motherTarget);
    commit(say(next.find(isMother) ?? mother, `${gone?.name ?? "That bot"} was removed from Wire.`, { motherStep: null, motherTarget: undefined }), next);
    return { bots: next };
  }

  commit(say(mother, "I don't know that yet. Send /help."));
  return { bots: next };
}
