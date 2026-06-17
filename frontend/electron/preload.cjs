const { contextBridge, ipcRenderer } = require("electron/renderer");

contextBridge.exposeInMainWorld("multiCraneDesktop", {
  openPath: (path) => ipcRenderer.invoke("desktop:openPath", path),
});
