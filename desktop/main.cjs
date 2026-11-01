'use strict';

const { app, BrowserWindow, Menu, dialog, ipcMain, shell, session } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { Backend, privateEnvironment, dataDirectory } = require('./lifecycle.cjs');
const { nativeKey, configureConnection } = require('./provider-connection.cjs');

let window = null;
let backend = null;
let origin = null;
let quitting = false;
let voice = null;
let smokeDataDirectory = null;
const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..');
const smoke = process.argv.includes('--desktop-smoke');
const backendDataDirectory = dataDirectory(app.getPath('appData'));
app.setName('aethon');
app.setAppUserModelId('io.github.mason5052.aethon');
app.setPath('userData', smoke ? fs.mkdtempSync(path.join(os.tmpdir(), 'smd-desktop-profile-')) :
  path.join(app.getPath('appData'), 'aethon', 'desktop'));

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (window) { window.restore(); window.show(); window.focus(); } });
  app.whenReady().then(start).catch(async () => {
    if (!smoke) dialog.showErrorBox('aethon', 'The local application could not start. Quit the application and try again.');
    app.quit();
  });
}

function trusted(event) {
  return !!window && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame &&
    !!origin && new URL(event.senderFrame.url).origin === origin;
}

function handle(channel, action) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (!trusted(event)) throw new Error('This action requires the local application window.');
    return action(...args);
  });
}

async function chooseFolder() {
  const selected = await dialog.showOpenDialog(window, { title: 'Choose a workspace',
    properties: ['openDirectory'], buttonLabel: 'Choose workspace' });
  return { canceled: selected.canceled, paths: selected.filePaths };
}

async function start() {
  const privateSession = session.fromPartition('smd-private');
  privateSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === window?.webContents && permission === 'media' && !!origin &&
      details.requestingUrl?.startsWith(origin + '/') && details.mediaTypes?.every(type => type === 'audio'));
  });
  privateSession.setPermissionCheckHandler((contents, permission, requestingOrigin) =>
    contents === window?.webContents && requestingOrigin === origin && permission === 'media');
  window = new BrowserWindow({ width: 1340, height: 900, minWidth: 840, minHeight: 600,
    backgroundColor: '#c0c0c0', show: true, title: 'aethon',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true, webSecurity: true, partition: 'smd-private',
      devTools: !app.isPackaged } });
  await window.loadFile(path.join(__dirname, 'starting.html'));
  window.webContents.setWindowOpenHandler(({ url }) => {
    const target = new URL(url);
    if (target.protocol === 'https:' && ['huggingface.co', 'github.com'].includes(target.hostname)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!origin || new URL(url).origin !== origin) event.preventDefault();
  });
  handle('smd:choose-folder', chooseFolder);
  handle('smd:hardware', () => ({ arch: process.arch, total_memory_bytes: os.totalmem(), free_memory_bytes: os.freemem() }));
  handle('smd:configure-provider', input => {
    const helper = path.join(app.isPackaged ? root : path.join(root, 'build', 'desktop'), 'helpers', 'aethon-key-entry');
    const icon = app.isPackaged ? path.join(root, 'aethon.icns') : path.join(root, 'build', 'desktop', 'artwork', 'icon.png');
    return configureConnection(origin, input, provider => nativeKey(helper, provider, icon));
  });
  handle('smd:open-files', async () => {
    const selected = await dialog.showOpenDialog(window, { title: 'Choose documents',
      properties: ['openFile', 'multiSelections'], filters: [
        { name: 'Documents and images', extensions: ['pdf', 'docx', 'pptx', 'txt', 'md', 'csv', 'json', 'png', 'jpg', 'jpeg', 'webp'] },
      ] });
    return { canceled: selected.canceled, paths: selected.filePaths };
  });
  handle('smd:minimize', () => window.minimize());
  handle('smd:close', () => app.quit());
  handle('smd:speak', text => {
    if (typeof text !== 'string' || !text.trim() || text.length > 10000 || text.includes('\0')) throw new Error('Choose up to 10,000 characters to read aloud.');
    if (process.platform !== 'darwin') throw new Error('System speech is currently available on macOS.');
    if (voice) voice.kill();
    voice = spawn('/usr/bin/say', [], { env: privateEnvironment(process.env), stdio: ['pipe', 'ignore', 'ignore'] });
    voice.on('error', () => { voice = null; });
    voice.stdin.end(text);
    return { started: true };
  });
  handle('smd:stop-speaking', () => { if (voice) voice.kill(); voice = null; });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: app.name, submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' }, { type: 'separator' }, { role: 'quit' }] },
    { label: 'File', submenu: [{ label: 'Open Workspace...', accelerator: 'CmdOrCtrl+O', click: async () => {
      const selection = await chooseFolder();
      if (!selection.canceled) window?.webContents.send('smd:workspace-selected', selection);
    } }, { type: 'separator' }, { role: 'close' }] },
    { role: 'editMenu' }, { role: 'windowMenu' },
  ]));
  const resourceRuntimes = app.isPackaged ? path.join(root, 'runtimes') : path.join(root, 'build', 'desktop', 'runtimes');
  const overrides = {};
  const opencode = path.join(resourceRuntimes, 'opencode', 'opencode');
  const ollama = path.join(resourceRuntimes, 'ollama');
  const mlxPython = path.join(resourceRuntimes, 'mlx', 'smd-mlx-runtime');
  const office = path.join(resourceRuntimes, 'LibreOffice.app', 'Contents', 'MacOS', 'soffice');
  const support = path.join(resourceRuntimes, 'opencode-support');
  if (fs.existsSync(opencode)) { overrides.SMD_OPENCODE_BINARY = opencode; overrides.SMD_OPENCODE = opencode; }
  if (fs.existsSync(ollama)) overrides.SMD_BUNDLED_OLLAMA_DIR = ollama;
  if (fs.existsSync(mlxPython)) overrides.SMD_MLX_PYTHON = mlxPython;
  if (fs.existsSync(office)) overrides.SMD_LIBREOFFICE = office;
  if (fs.existsSync(support)) overrides.SMD_OPENCODE_SUPPORT_DIR = support;
  const service = app.isPackaged ? path.join(root, 'service', 'smd-desktop-service') :
    path.join(root, '.venv', 'bin', 'python');
  const args = app.isPackaged ? [] : ['-m', 'smd_app.desktop_server'];
  args.push('--data-dir', backendDataDirectory, '--parent-pid', String(process.pid));
  if (smoke) {
    const temporaryData = fs.mkdtempSync(path.join(os.tmpdir(), 'smd-desktop-smoke-'));
    smokeDataDirectory = temporaryData;
    args[args.indexOf('--data-dir') + 1] = temporaryData;
  }
  backend = new Backend(service, args, { env: privateEnvironment(process.env, overrides), cwd: root });
  backend.on('unexpected-exit', () => {
    if (!quitting) { dialog.showErrorBox(app.name, 'The local service stopped. Reopen the application to continue.'); app.quit(); }
  });
  origin = await backend.start();
  await window.loadURL(origin);
  if (smoke) {
    await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
      const started = Date.now();
      const timer = setInterval(() => {
        if (document.getElementById('server-state-text')?.textContent === 'On this computer') {
          clearInterval(timer); setTimeout(resolve, 500);
        } else if (Date.now() - started > 20000) {
          clearInterval(timer); reject(new Error('The desktop interface did not initialize.'));
        }
      }, 100);
    })`);
    const result = await window.webContents.executeJavaScript(`(async () => {
      const session = await fetch('/api/v1/session').then(r => r.json());
      const status = await fetch('/api/v1/status').then(r => r.json());
      return { title: document.title, bridge: !!window.smdDesktop, platform: window.smdDesktop?.platform,
        authorized: typeof session.token === 'string', runtimeReady: status.runtime?.ready,
        engineReady: status.runtime?.runtime_ready, mlxAvailable: status.runtime?.engines?.mlx?.available,
        visiblePasswordFields: Array.from(document.querySelectorAll('input[type=password]')).filter(x => x.offsetParent !== null).length,
        nativeKeyEntry: typeof window.smdDesktop?.configureProvider === 'function',
        origin: location.origin, nodeExposed: typeof window.require !== 'undefined' };
    })()`);
    process.stdout.write(JSON.stringify({ desktopSmoke: result }) + '\n');
    const capture = await window.webContents.capturePage();
    const capturePath = app.isPackaged ? path.join(os.tmpdir(), 'aethon-packaged-desktop-smoke.png') : path.join(root, 'build', 'desktop', 'smoke.png');
    fs.writeFileSync(capturePath, capture.toPNG());
    await window.webContents.executeJavaScript(`document.querySelector('[data-view="work"]').click(); new Promise(resolve => setTimeout(resolve, 500))`);
    fs.writeFileSync(path.join(os.tmpdir(), 'aethon-workspace.png'), (await window.webContents.capturePage()).toPNG());
    app.quit();
  }
}

app.on('activate', () => { if (window) { window.show(); window.focus(); } });
app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if (quitting) return;
  event.preventDefault();
  quitting = true;
  if (voice) voice.kill();
  Promise.resolve(backend?.stop()).finally(() => {
    if (smoke) {
      const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
      process.stdout.write(JSON.stringify({ desktopShutdown: { backendStopped: !backend?.child || !alive(backend.child.pid),
        engineChildrenStopped: (backend?.childPids || []).every(pid => !alive(pid)) } }) + '\n');
      if (smokeDataDirectory) fs.rmSync(smokeDataDirectory, { recursive: true, force: true });
    }
    app.quit();
  });
});
