const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wire", {
  selectScript: () => ipcRenderer.invoke("wire:select-script"),
  getDefaultScript: () => ipcRenderer.invoke("wire:default-script"),
  openBotLog: (port) => ipcRenderer.invoke("wire:open-bot-log", port),
  startBot: (config) => ipcRenderer.invoke("wire:start-bot", config),
  stopBot: (port) => ipcRenderer.invoke("wire:stop-bot", port),
});
