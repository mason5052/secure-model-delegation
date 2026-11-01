'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const chooseFolder = () => ipcRenderer.invoke('smd:choose-folder');
const openFiles = () => ipcRenderer.invoke('smd:open-files');
contextBridge.exposeInMainWorld('smdDesktop', Object.freeze({
  platform: process.platform,
  version: '0.3.0',
  hardware: () => ipcRenderer.invoke('smd:hardware'),
  configureProvider: configuration => ipcRenderer.invoke('smd:configure-provider', configuration),
  chooseFolder,
  chooseWorkspace: chooseFolder,
  openFiles,
  chooseFiles: openFiles,
  minimize: () => ipcRenderer.invoke('smd:minimize'),
  close: () => ipcRenderer.invoke('smd:close'),
  speak: text => ipcRenderer.invoke('smd:speak', text),
  stopSpeaking: () => ipcRenderer.invoke('smd:stop-speaking'),
  onWorkspaceSelected: callback => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, selection) => callback(selection);
    ipcRenderer.on('smd:workspace-selected', listener);
    return () => ipcRenderer.removeListener('smd:workspace-selected', listener);
  },
}));
