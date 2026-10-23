const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wire", {
  selectScript: () => ipcRenderer.invoke("wire:select-script"),
  getDefaultScript: () => ipcRenderer.invoke("wire:default-script"),
  startBot: (config) => ipcRenderer.invoke("wire:start-bot", config),
  stopBot: (port) => ipcRenderer.invoke("wire:stop-bot", port),
});
