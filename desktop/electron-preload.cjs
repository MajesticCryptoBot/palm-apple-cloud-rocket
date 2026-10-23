const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wire", {
  selectWallpaper: () => ipcRenderer.invoke("wire:select-wallpaper"),
  showNotification: (payload) => ipcRenderer.invoke("wire:show-notification", payload),
  bridgePoll: () => ipcRenderer.invoke("wire:bridge-poll"),
  bridgeCommand: (command) => ipcRenderer.invoke("wire:bridge-command", command),
});
