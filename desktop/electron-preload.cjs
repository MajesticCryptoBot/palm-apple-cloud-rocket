const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wire", {
  selectScript: () => ipcRenderer.invoke("wire:select-script"),
  selectWallpaper: () => ipcRenderer.invoke("wire:select-wallpaper"),
  showNotification: (payload) => ipcRenderer.invoke("wire:show-notification", payload),
  openBotLog: (port) => ipcRenderer.invoke("wire:open-bot-log", port),
  startBot: (config) => ipcRenderer.invoke("wire:start-bot", config),
  stopBot: (port) => ipcRenderer.invoke("wire:stop-bot", port),
});
