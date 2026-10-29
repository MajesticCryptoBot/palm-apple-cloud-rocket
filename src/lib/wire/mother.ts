import { createBot, uid, type Bot, type CommandSpec, type Exchange, type Message } from "@/lib/wire/engine";

export const MOTHER_ID = "botmother";

export const MOTHER_COMMANDS: CommandSpec[] = [
  { name: "/newbot", hint: "create a new bot", group: "Session" },
  { name: "/mybots", hint: "edit your bots", group: "Session" },
  { name: "/setname", hint: "change a bot's name", group: "Session" },
  { name: "/setdescription", hint: "change bot description", group: "Session" },
  { name: "/setabouttext", hint: "change bot about info", group: "Session" },
  { name: "/setuserpic", hint: "change bot profile photo", group: "Session" },
  { name: "/setcommands", hint: "change the list of commands", group: "Session" },
  { name: "/deletebot", hint: "delete a bot", group: "Session", danger: true },
  { name: "/token", hint: "get authorization token", group: "Session" },
  { name: "/revoke", hint: "revoke bot access token", group: "Session" },
  { name: "/setinline", hint: "toggle inline mode", group: "Session" },
  { name: "/setjoingroups", hint: "can your bot be added to groups", group: "Session" },
  { name: "/setprivacy", hint: "toggle privacy mode", group: "Session" },
  { name: "/cancel", hint: "cancel the current operation", group: "Session" },
  { name: "/help", hint: "command list", group: "Session" },
];

const HELP = [
  "I can help you create and manage Wire bots. Think of me as BotFather.",
  "",
  "You can control me by sending these commands:",
  "",
  "/newbot — create a new bot",
  "/mybots — edit your bots",
  "/setname — change a bot's name",
  "/setdescription — change bot description",
  "/setabouttext — change bot about info",
  "/setuserpic — change bot profile photo",
  "/setcommands — change the list of commands",
  "/deletebot — delete a bot",
  "/token — get authorization token",
  "/revoke — revoke bot access token",
  "/setinline — toggle inline mode",
  "/setjoingroups — can your bot be added to groups",
  "/setprivacy — toggle privacy mode",
  "/cancel — cancel the current operation",
].join("\n");

const FOLDERS: { name: string; exchange: Exchange; directory: string }[] = [
  { name: "ABinanceTradingBot", exchange: "Binance Testnet", directory: "ABINANCE TESTNET" },
  { name: "Binance Live Bot", exchange: "Binance", directory: "BINANCE LIVE" },
  { name: "Bitget Live Bot", exchange: "Bitget", directory: "Bitget Live Bot" },
  { name: "Bybit Live Bot", exchange: "Bybit", directory: "Bybit Live Bot" },
  { name: "GROK TESTNET", exchange: "Binance Testnet", directory: "GROK TESTNET" },
  { name: "ZZZBinance METRICS LIVE", exchange: "Binance", directory: "ZZZBinance METRICS LIVE" },
];

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
  bot.username = "BotMother";
  bot.pins = [];
  bot.motherStep = null;
  bot.messages = [line("bot", HELP, now)];
  return bot;
}

export function isMother(bot: Bot): boolean {
  return bot.id === MOTHER_ID || bot.source === "system";
}

function botsOnly(bots: Bot[]): Bot[] {
  return bots.filter((b) => !isMother(b) && b.kind !== "channel");
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
  const list = botsOnly(bots);
  if (!list.length) return "You have no bots yet. Send /newbot to create one.";
  return list.map((b, i) => `${i + 1}. ${b.name}${b.username ? ` @${b.username}` : ""}`).join("\n");
}

function byNumber(bots: Bot[], text: string): Bot | undefined {
  const n = Number(text.trim());
  const list = botsOnly(bots);
  if (!Number.isInteger(n) || n < 1 || n > list.length) return undefined;
  return list[n - 1];
}

function guessExchange(directory: string): Exchange {
  const d = directory.toLowerCase();
  if (d.includes("bitget")) return "Bitget";
  if (d.includes("bybit")) return "Bybit";
  if (d.includes("testnet") || d.includes("grok")) return "Binance Testnet";
  return "Binance";
}

function validUsername(raw: string): string | null {
  const name = raw.trim().replace(/^@/, "");
  if (!/^[A-Za-z][A-Za-z0-9_]{3,30}$/.test(name) || !/bot$/i.test(name)) return null;
  return name;
}

function blankTrading(name: string, username: string, directory: string, exchange: Exchange): Bot {
  const bot = createBot({ name, exchange, online: false, source: "bridge", commands: [] });
  bot.kind = "trading";
  bot.username = username;
  bot.bridgeDirectory = directory;
  bot.token = `${uid("tok")}:${uid("sec")}`;
  bot.joinGroups = true;
  bot.privacy = true;
  bot.inlineMode = false;
  bot.about = "";
  bot.description = "";
  bot.pins = [];
  bot.messages = [line("service", "Bot created. Open Menu after you set commands with /setcommands.")];
  bot.inbox = [];
  bot.wallet = {};
  bot.history = [];
  bot.prices = {};
  return bot;
}

function blankPublisher(name: string, username: string, directory: string): Bot {
  const bot = createBot({ name, exchange: "Wire", online: true, source: "custom", commands: [] });
  bot.kind = "publisher";
  bot.username = username;
  bot.bridgeDirectory = directory;
  bot.token = `${uid("tok")}:${uid("sec")}`;
  bot.joinGroups = true;
  bot.privacy = true;
  bot.inlineMode = false;
  bot.about = "Publishes posts into a channel.";
  bot.description = "Add this bot as a channel administrator. It posts whatever your script writes to asp_channel_feed.json.";
  bot.pins = [];
  bot.messages = [line("service", `${name} publishes into a channel. Add it under the channel's Administrators.`)];
  bot.inbox = [];
  return bot;
}

function blankCustom(name: string, username: string): Bot {
  const bot = createBot({
    name,
    exchange: "Wire",
    online: true,
    source: "custom",
    commands: [
      { name: "/start", hint: "Start", group: "Session" },
      { name: "/help", hint: "Help", group: "Session" },
    ],
  });
  bot.kind = "custom";
  bot.username = username;
  bot.token = `${uid("tok")}:${uid("sec")}`;
  bot.joinGroups = true;
  bot.privacy = true;
  bot.inlineMode = false;
  bot.pins = [];
  bot.messages = [line("bot", `${name} is ready. Use /setcommands to edit its menu.`)];
  bot.inbox = [];
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
      if (file.size > 1_500_000) return resolve("too-big");
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : null);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(file);
    };
    input.click();
  });
}

function parseCommands(raw: string): CommandSpec[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [rawName, ...desc] = line.split("|");
      const name = rawName.trim();
      return {
        name: name.startsWith("/") ? name : `/${name}`,
        hint: desc.join("|").trim() || "Command",
        group: "Session" as const,
        danger: /sell|reset|emergency|buy|withdraw|delete/i.test(name),
      };
    })
    .filter((command) => /^\/[a-zA-Z0-9_]{1,50}$/.test(command.name));
}

function menu(bot: Bot): string {
  return [
    `Here it is: ${bot.name}${bot.username ? ` @${bot.username}` : ""}`,
    "",
    "What do you want to do with the bot?",
    "",
    "1. API Token",
    "2. Edit Bot",
    "3. Bot Settings",
    "4. Delete Bot",
    "",
    "Send the number, or /cancel.",
  ].join("\n");
}

function editMenu(): string {
  return ["Edit Bot", "", "1. Edit Name", "2. Edit About", "3. Edit Description", "4. Edit Botpic", "5. Edit Commands", "6. « Back"].join("\n");
}

function settingsMenu(bot: Bot): string {
  return [
    "Bot Settings",
    "",
    `1. Inline Mode — ${bot.inlineMode ? "on" : "off"}`,
    `2. Allow Groups — ${bot.joinGroups === false ? "off" : "on"}`,
    `3. Group Privacy — ${bot.privacy === false ? "off" : "on"}`,
    "4. « Back",
  ].join("\n");
}

export async function applyMother(bots: Bot[], text: string): Promise<{ bots: Bot[] }> {
  const raw = text.trim();
  const cmd = raw.split(/\s+/)[0]?.toLowerCase() ?? "";
  let next = bots.map((b) => ({ ...b }));
  const found = next.find(isMother);
  if (!found) return { bots };
  let mother: Bot = found;

  const commit = (updated: Bot, all = next) => {
    next = all.map((b) => (isMother(b) ? updated : b));
    mother = updated;
  };

  if (cmd === "/cancel") {
    commit(say(hear(mother, raw), "Cancelled. What would you like to do next? Send /help to see the list.", { motherStep: null, motherTarget: undefined, motherDraft: undefined }));
    return { bots: next };
  }
  if (cmd === "/start" || cmd === "/help") {
    commit(say(hear(mother, raw), HELP, { motherStep: null, motherTarget: undefined, motherDraft: undefined }));
    return { bots: next };
  }
  if (cmd === "/newchannel") {
    commit(say(hear(mother, raw), "Channels are not created here.\n\nTap the + button, then New Channel. That is the same place Telegram uses.", { motherStep: null }));
    return { bots: next };
  }
  if (cmd === "/newbot") {
    commit(say(hear(mother, raw), "Alright, a new bot. How are we going to call it? Please choose a name for your bot.", { motherStep: "newbot-name", motherTarget: undefined, motherDraft: undefined }));
    return { bots: next };
  }
  if (cmd === "/mybots") {
    commit(say(hear(mother, raw), `Choose a bot to manage.\n\n${roster(next)}`, { motherStep: "mybots-pick", motherTarget: undefined }));
    return { bots: next };
  }

  const direct = ["/setname", "/setdescription", "/setabouttext", "/setuserpic", "/setphoto", "/setcommands", "/deletebot", "/token", "/revoke", "/setinline", "/setjoingroups", "/setprivacy"];
  if (direct.includes(cmd)) {
    const step =
      cmd === "/setname" ? "setname-pick"
      : cmd === "/setdescription" ? "desc-pick"
      : cmd === "/setabouttext" ? "about-pick"
      : cmd === "/setuserpic" || cmd === "/setphoto" ? "pic-pick"
      : cmd === "/setcommands" ? "commands-pick"
      : cmd === "/deletebot" ? "delete-pick"
      : cmd === "/token" ? "token-pick"
      : cmd === "/revoke" ? "revoke-pick"
      : cmd === "/setinline" ? "inline-pick"
      : cmd === "/setjoingroups" ? "groups-pick"
      : "privacy-pick";
    commit(say(hear(mother, raw), `Choose a bot.\n\n${roster(next)}`, { motherStep: step, motherTarget: undefined }));
    return { bots: next };
  }

  if (!raw.startsWith("/") && mother.motherStep) {
    const heard = hear(mother, raw);
    if (mother.motherStep === "newbot-name") {
      const name = raw.replace(/\s+/g, " ").slice(0, 48);
      if (name.length < 1) {
        commit(say(heard, "Please choose a name for your bot."));
        return { bots: next };
      }
      commit(say(heard, "Good. Now let's choose a username for your bot. It must end in `bot`. Like this, for example: TetrisBot or tetris_bot.", { motherStep: "newbot-username", motherDraft: name }));
      return { bots: next };
    }
    if (mother.motherStep === "newbot-username") {
      const username = validUsername(raw);
      if (!username) {
        commit(say(heard, "Sorry, this username is invalid.\n\nA username must end in bot and can only contain letters, numbers and underscores."));
        return { bots: next };
      }
      if (botsOnly(next).some((b) => b.username?.toLowerCase() === username.toLowerCase())) {
        commit(say(heard, "Sorry, this username is already taken. Please try something different."));
        return { bots: next };
      }
      commit(say(heard, "What should this bot run?\n\n1. A trading script\n2. A news publisher for a channel\n3. A custom bot\n\nSend 1, 2 or 3.", { motherStep: "newbot-role", motherTarget: username }));
      return { bots: next };
    }
    if (mother.motherStep === "newbot-role") {
      if (raw === "3" || /custom/i.test(raw)) {
        const created = blankCustom(mother.motherDraft || "Bot", mother.motherTarget || "custombot");
        commit(say(heard, doneText(created), { motherStep: null, motherDraft: undefined, motherTarget: undefined }), [...next, created]);
        return { bots: next };
      }
      if (raw === "1" || /trad/i.test(raw) || raw === "2" || /news|publish/i.test(raw)) {
        const role = raw === "2" || /news|publish/i.test(raw) ? "publisher" : "trading";
        const free = FOLDERS.filter((p) => !next.some((b) => b.bridgeDirectory === p.directory));
        const choices = free.length ? free.map((p, i) => `${i + 1}. ${p.directory}`).join("\n") : "Type a Desktop folder name, for example ASP NEWS.";
        commit(say(heard, `Send the folder name on your Desktop. Your script must live in that folder.\n\n${choices}`, { motherStep: "newbot-folder", motherDraft: `${role}|${mother.motherDraft || ""}|${mother.motherTarget || ""}` }));
        return { bots: next };
      }
      commit(say(heard, "Send 1, 2 or 3."));
      return { bots: next };
    }
    if (mother.motherStep === "newbot-folder") {
      const [role, name, username] = (mother.motherDraft || "trading|Bot|newbot").split("|");
      const free = FOLDERS.filter((p) => !next.some((b) => b.bridgeDirectory === p.directory));
      const n = Number(raw);
      const picked = Number.isInteger(n) && n >= 1 && n <= free.length ? free[n - 1] : undefined;
      const directory = picked?.directory ?? raw;
      if (!directory || directory.startsWith("/")) {
        commit(say(heard, "Send a folder name, or /cancel."));
        return { bots: next };
      }
      const created = role === "publisher"
        ? blankPublisher(name || "News bot", username || "newsbot", directory)
        : blankTrading(picked?.name && !name ? picked.name : name || picked?.name || "Bot", username || "tradebot", directory, picked?.exchange ?? guessExchange(directory));
      void window.wire?.ensureFeed?.(directory);
      commit(say(heard, doneText(created) + (role === "publisher" ? `\n\nFolder: Desktop\\${directory}\nYour ASP News script posts into a channel when it writes asp_channel_feed.json there.\nThen open the channel, tap the name, and add this bot under Administrators.` : `\n\nFolder: Desktop\\${directory}`), { motherStep: null, motherDraft: undefined, motherTarget: undefined }), [...next, created]);
      return { bots: next };
    }

    const picked = ["mybots-pick", "setname-pick", "desc-pick", "about-pick", "pic-pick", "commands-pick", "delete-pick", "token-pick", "revoke-pick", "inline-pick", "groups-pick", "privacy-pick"].includes(mother.motherStep);
    if (picked) {
      const target = byNumber(next, raw);
      if (!target) {
        commit(say(heard, `Send a number from this list.\n\n${roster(next)}`));
        return { bots: next };
      }
      if (mother.motherStep === "mybots-pick") {
        commit(say(heard, menu(target), { motherStep: "mybots-menu", motherTarget: target.id }));
        return { bots: next };
      }
      if (mother.motherStep === "setname-pick") {
        commit(say(heard, "OK. Send me the new name for your bot.", { motherStep: "setname-value", motherTarget: target.id }));
        return { bots: next };
      }
      if (mother.motherStep === "desc-pick") {
        commit(say(heard, "OK. Send me the new description for the bot. People will see this description when they open a chat with your bot.", { motherStep: "desc-value", motherTarget: target.id }));
        return { bots: next };
      }
      if (mother.motherStep === "about-pick") {
        commit(say(heard, "OK. Send me the new 'About' text. People will see this text on the bot's profile page.", { motherStep: "about-value", motherTarget: target.id }));
        return { bots: next };
      }
      if (mother.motherStep === "commands-pick") {
        commit(say(heard, "OK. Send me a list of commands for your bot. Use this format:\n\ncommand1 - Description\ncommand2 - Another description\n\nSend /empty to keep the menu clear.", { motherStep: "commands-value", motherTarget: target.id }));
        return { bots: next };
      }
      if (mother.motherStep === "delete-pick") {
        commit(say(heard, `You are about to delete ${target.name}.\n\nSend YES to confirm, or /cancel.`, { motherStep: "delete-confirm", motherTarget: target.id }));
        return { bots: next };
      }
      if (mother.motherStep === "token-pick") {
        commit(say(heard, tokenText(target), { motherStep: null, motherTarget: undefined }));
        return { bots: next };
      }
      if (mother.motherStep === "revoke-pick") {
        const token = `${uid("tok")}:${uid("sec")}`;
        next = next.map((b) => (b.id === target.id ? { ...b, token } : b));
        commit(say(next.find(isMother) ?? heard, `Done. The old token is no longer valid.\n\nNew token:\n${token}`, { motherStep: null, motherTarget: undefined }), next);
        return { bots: next };
      }
      if (mother.motherStep === "inline-pick" || mother.motherStep === "groups-pick" || mother.motherStep === "privacy-pick") {
        const key = mother.motherStep === "inline-pick" ? "inlineMode" : mother.motherStep === "groups-pick" ? "joinGroups" : "privacy";
        const current = target[key];
        const on = key === "inlineMode" ? !current : current === false;
        next = next.map((b) => (b.id === target.id ? { ...b, [key]: on } : b));
        const label = key === "inlineMode" ? "Inline mode" : key === "joinGroups" ? "Allow groups" : "Group privacy";
        commit(say(next.find(isMother) ?? heard, `${label} is now ${on ? "enabled" : "disabled"} for ${target.name}.`, { motherStep: null, motherTarget: undefined }), next);
        return { bots: next };
      }
      const photo = await pickImage();
      if (!photo || photo === "too-big") {
        commit(say(heard, photo === "too-big" ? "That picture is too large. Choose one under 1 MB." : "No picture selected. Send /setuserpic to try again.", { motherStep: null, motherTarget: undefined }));
        return { bots: next };
      }
      next = next.map((b) => (b.id === target.id ? { ...b, photo } : b));
      commit(say(next.find(isMother) ?? heard, "Profile photo updated.", { motherStep: null, motherTarget: undefined }), next);
      return { bots: next };
    }

    if (mother.motherStep === "mybots-menu" && mother.motherTarget) {
      const target = next.find((b) => b.id === mother.motherTarget);
      if (!target) {
        commit(say(heard, "That bot is gone. Send /mybots.", { motherStep: null, motherTarget: undefined }));
        return { bots: next };
      }
      if (raw === "1") {
        commit(say(heard, tokenText(target), { motherStep: "mybots-menu" }));
        return { bots: next };
      }
      if (raw === "2") {
        commit(say(heard, editMenu(), { motherStep: "edit-menu" }));
        return { bots: next };
      }
      if (raw === "3") {
        commit(say(heard, settingsMenu(target), { motherStep: "settings-menu" }));
        return { bots: next };
      }
      if (raw === "4") {
        commit(say(heard, `You are about to delete ${target.name}.\n\nSend YES to confirm, or /cancel.`, { motherStep: "delete-confirm" }));
        return { bots: next };
      }
      commit(say(heard, "Send 1, 2, 3 or 4."));
      return { bots: next };
    }

    if (mother.motherStep === "edit-menu" && mother.motherTarget) {
      if (raw === "6") {
        const target = next.find((b) => b.id === mother.motherTarget);
        commit(say(heard, target ? menu(target) : "Send /mybots.", { motherStep: "mybots-menu" }));
        return { bots: next };
      }
      const step = raw === "1" ? "setname-value" : raw === "2" ? "about-value" : raw === "3" ? "desc-value" : raw === "5" ? "commands-value" : "";
      if (step) {
        const prompt = raw === "1" ? "OK. Send me the new name for your bot." : raw === "2" ? "OK. Send me the new 'About' text." : raw === "3" ? "OK. Send me the new description for the bot." : "OK. Send commands, one per line:\ncommand - Description";
        commit(say(heard, prompt, { motherStep: step }));
        return { bots: next };
      }
      if (raw === "4") {
        const photo = await pickImage();
        if (!photo || photo === "too-big") {
          commit(say(heard, photo === "too-big" ? "That picture is too large." : "No picture selected.", { motherStep: "edit-menu" }));
          return { bots: next };
        }
        next = next.map((b) => (b.id === mother.motherTarget ? { ...b, photo } : b));
        commit(say(next.find(isMother) ?? heard, "Success! Profile photo updated. /mybots", { motherStep: null, motherTarget: undefined }), next);
        return { bots: next };
      }
      commit(say(heard, "Send a number from the list."));
      return { bots: next };
    }

    if (mother.motherStep === "settings-menu" && mother.motherTarget) {
      const target = next.find((b) => b.id === mother.motherTarget);
      if (!target) return { bots: next };
      if (raw === "4") {
        commit(say(heard, menu(target), { motherStep: "mybots-menu" }));
        return { bots: next };
      }
      const key = raw === "1" ? "inlineMode" : raw === "2" ? "joinGroups" : raw === "3" ? "privacy" : "";
      if (!key) {
        commit(say(heard, "Send 1, 2, 3 or 4."));
        return { bots: next };
      }
      const current = target[key as "inlineMode"];
      const on = key === "inlineMode" ? !current : current === false;
      next = next.map((b) => (b.id === target.id ? { ...b, [key]: on } : b));
      const fresh = next.find((b) => b.id === target.id) ?? target;
      commit(say(next.find(isMother) ?? heard, settingsMenu(fresh), { motherStep: "settings-menu" }), next);
      return { bots: next };
    }

    if (mother.motherStep === "setname-value" && mother.motherTarget) {
      const name = raw.replace(/\s+/g, " ").slice(0, 48);
      next = next.map((b) => (b.id === mother.motherTarget ? { ...b, name } : b));
      commit(say(next.find(isMother) ?? heard, "Success! Name updated. /mybots", { motherStep: null, motherTarget: undefined, motherDraft: undefined }), next);
      return { bots: next };
    }
    if (mother.motherStep === "about-value" && mother.motherTarget) {
      next = next.map((b) => (b.id === mother.motherTarget ? { ...b, about: raw } : b));
      commit(say(next.find(isMother) ?? heard, "Success! About text updated. /mybots", { motherStep: null, motherTarget: undefined }), next);
      return { bots: next };
    }
    if (mother.motherStep === "desc-value" && mother.motherTarget) {
      next = next.map((b) => (b.id === mother.motherTarget ? { ...b, description: raw } : b));
      commit(say(next.find(isMother) ?? heard, "Success! Description updated. /mybots", { motherStep: null, motherTarget: undefined }), next);
      return { bots: next };
    }
    if (mother.motherStep === "commands-value" && mother.motherTarget) {
      const commands = raw.toLowerCase() === "/empty" ? [] : parseCommands(raw.replace(/ - /g, " | "));
      if (!commands.length && raw.toLowerCase() !== "/empty") {
        commit(say(heard, "I could not read any commands. Use:\nstart - Start the bot"));
        return { bots: next };
      }
      next = next.map((b) => (b.id === mother.motherTarget ? { ...b, commands } : b));
      commit(say(next.find(isMother) ?? heard, "Success! Command list updated. /mybots", { motherStep: null, motherTarget: undefined }), next);
      return { bots: next };
    }
    if (mother.motherStep === "delete-confirm" && mother.motherTarget) {
      if (raw.toUpperCase() !== "YES") {
        commit(say(heard, "Not deleted. Send YES to confirm, or /cancel."));
        return { bots: next };
      }
      const gone = next.find((b) => b.id === mother.motherTarget);
      next = next.filter((b) => b.id !== mother.motherTarget).map((b) => (b.kind === "channel" ? { ...b, admins: (b.admins ?? []).filter((id) => id !== mother.motherTarget) } : b));
      const updated = next.find(isMother) ?? heard;
      commit(say(updated, `Done. ${gone?.name ?? "The bot"} has been deleted.`, { motherStep: null, motherTarget: undefined }), next);
      return { bots: next };
    }
  }

  commit(say(hear(mother, raw), "Unknown command. Send /help to see what I can do."));
  return { bots: next };
}

function doneText(bot: Bot): string {
  return [
    "Done! Congratulations on your new bot.",
    "",
    `You can find it in your chat list as ${bot.name}${bot.username ? ` @${bot.username}` : ""}.`,
    "",
    "Use this token to access the bot:",
    bot.token || "",
    "",
    "Keep your token secure. Send /mybots to edit this bot later.",
  ].join("\n");
}

function tokenText(bot: Bot): string {
  return [`${bot.name}${bot.username ? ` @${bot.username}` : ""}`, "", "Use this token:", bot.token || "This bot has no token yet. Send /revoke to create one."].join("\n");
}
