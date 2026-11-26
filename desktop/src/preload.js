const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  call: (cmd, args) => ipcRenderer.invoke('engine:call', cmd, args),
  on: (name, fn) => {
    const handler = (_e, evName, data) => {
      if (evName === name) fn(data);
    };
    ipcRenderer.on('engine:event', handler);
    return () => ipcRenderer.removeListener('engine:event', handler);
  },
  ui: (action, payload) => ipcRenderer.invoke('ui', action, payload),
});
