'use strict';

const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const origin = process.argv[2];
const projectId = process.argv[3];
const documentName = process.argv[4] || 'synthetic-report.docx';
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin || '') || !/^[a-f0-9]{32}$/.test(projectId || '') ||
    !/^[A-Za-z0-9_. -]+\.docx$/.test(documentName)) {
  throw new Error('Provide a loopback origin, synthetic project ID, and document basename.');
}
let window;

async function waitFor(expression, timeout = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await window.webContents.executeJavaScript(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error('The synthetic preview did not become ready.');
}

app.whenReady().then(async () => {
  ipcMain.handle('smd:hardware', () => ({ arch: process.arch, total_memory_bytes: os.totalmem(), free_memory_bytes: os.freemem() }));
  window = new BrowserWindow({ width: 1440, height: 1050, show: true,
    webPreferences: { preload: path.resolve(__dirname, '../preload.cjs'), nodeIntegration: false,
      contextIsolation: true, sandbox: true, webSecurity: true, partition: 'aethon-preview-proof' } });
  await window.loadURL(origin);
  await waitFor(`document.getElementById('server-state-text')?.textContent === 'On this computer'`);
  await window.webContents.executeJavaScript(`document.querySelector('[data-view="work"]').click()`);
  await waitFor(`Array.from(document.querySelector('#project-select').options).some(option=>option.value===${JSON.stringify(projectId)})`);
  await window.webContents.executeJavaScript(`const select=document.getElementById('project-select'); select.value=${JSON.stringify(projectId)}; select.dispatchEvent(new Event('change',{bubbles:true}))`);
  await waitFor(`document.getElementById('work-tools')?.hidden === false`);
  await window.webContents.executeJavaScript(`document.querySelector('[data-work-tool="documents"]').click(); document.getElementById('document-open').click()`);
  await waitFor(`!!document.querySelector('dialog[open] #dialog-path')`);
  await window.webContents.executeJavaScript(`document.getElementById('dialog-path').value=${JSON.stringify(documentName)}; document.getElementById('dialog-form').requestSubmit()`);
  await waitFor(`Array.from(document.querySelectorAll('#document-content button')).some(button=>button.textContent.includes('Preview as PDF'))`);
  await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#document-content button')).find(button=>button.textContent.includes('Preview as PDF')).click()`);
  await waitFor(`!!document.querySelector('#document-preview canvas.pdf-page') && document.querySelector('#document-preview .pdf-toolbar .mono')?.textContent === '1 / 1'`, 60000);
  await window.webContents.executeJavaScript(`document.getElementById('document-preview').scrollIntoView({block:'start'}); document.querySelector('.pdf-surface').scrollTop=0`);
  await new Promise(resolve => setTimeout(resolve, 500));
  fs.writeFileSync('/private/tmp/aethon-pdf.png', (await window.webContents.capturePage()).toPNG());
  console.log('Synthetic PDF preview capture saved.');
  app.quit();
}).catch(error => { console.error(error.message); app.exit(1); });
