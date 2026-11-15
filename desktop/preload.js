const { contextBridge, ipcRenderer } = require('electron')

const managed = process.argv.includes('--tabscribe-managed')
const on = channel => cb => {
  const fn = (_e, x) => cb(x)
  ipcRenderer.on(channel, fn)
  return () => ipcRenderer.removeListener(channel, fn)
}

contextBridge.exposeInMainWorld('tabscribe', {
  isDesktop: true,
  platform: process.platform,
  share: files => ipcRenderer.invoke('share', files),
  // first-run setup / component manager (packaged app only)
  setup: managed ? {
    status: () => ipcRenderer.invoke('setup:status'),
    install: (ids, opts = {}) => ipcRenderer.invoke('setup:install', { ids, ...opts }),
    cancel: () => ipcRenderer.invoke('setup:cancel'),
    verify: () => ipcRenderer.invoke('setup:verify'),
    remove: id => ipcRenderer.invoke('setup:remove', id),
    launch: () => ipcRenderer.invoke('setup:launch'),
    open: () => ipcRenderer.invoke('setup:open'),
    reveal: () => ipcRenderer.invoke('setup:reveal'),
    logs: () => ipcRenderer.invoke('setup:logs'),
    onProgress: on('setup:progress'),
    onRetry: on('setup:retry'),
    onVerifyStep: on('setup:verify-step'),
  } : null,
})
