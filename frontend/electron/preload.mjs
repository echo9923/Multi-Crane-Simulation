import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("multiCraneDesktop", {
  openPath: (path) => ipcRenderer.invoke("desktop:openPath", path),
});
