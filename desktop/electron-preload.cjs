const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wire", {
  selectWallpaper: () => ipcRenderer.invoke("wire:select-wallpaper"),
  showNotification: (payload) => ipcRenderer.invoke("wire:show-notification", payload),
  bridgePoll: (directory) => ipcRenderer.invoke("wire:bridge-poll", directory),
  bridgeCommand: (command, directory) => ipcRenderer.invoke("wire:bridge-command", { command, directory }),
  ensureFeed: (directory) => ipcRenderer.invoke("wire:ensure-feed", directory),
});
