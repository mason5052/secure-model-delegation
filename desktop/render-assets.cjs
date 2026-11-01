'use strict';

const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const [svgPath, output] = process.argv.slice(2);
app.on('window-all-closed', () => {});

async function render(html, width, height, destination) {
  const window = new BrowserWindow({ width, height, useContentSize: true, show: false,
    backgroundColor: '#00000000', transparent: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
  await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  await window.webContents.executeJavaScript('Promise.all(Array.from(document.images, image => image.decode()))');
  const image = await window.webContents.capturePage();
  fs.writeFileSync(destination, image.resize({ width, height, quality: 'best' }).toPNG());
  window.destroy();
}

app.whenReady().then(async () => {
  const source = fs.readFileSync(svgPath, 'utf8');
  const image = 'data:image/svg+xml;base64,' + Buffer.from(source).toString('base64');
  const policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">';
  await render(`${policy}<style>html,body{margin:0;overflow:hidden;background:transparent}img{width:1024px;height:1024px}</style><img src="${image}">`,
    1024, 1024, path.join(output, 'icon.png'));
  await render(`${policy}<style>*{box-sizing:border-box}html,body{margin:0;width:660px;height:420px;overflow:hidden;background:#c7c7c7;color:#18263b;font-family:Geneva,Arial,sans-serif}
  body{border:2px solid #222;box-shadow:inset 2px 2px #fff,inset -2px -2px #777}header{height:28px;border-bottom:1px solid #333;background:repeating-linear-gradient(#ddd 0 2px,#999 2px 3px,#ddd 3px 4px);text-align:center;padding-top:5px}header span{padding:0 14px;background:#c7c7c7;font-weight:bold;font-size:13px}
  img{position:absolute;left:29px;top:50px;width:85px;height:85px}h1{position:absolute;left:131px;top:45px;margin:0;font-size:36px;font-weight:700;letter-spacing:-1px}p{position:absolute;left:133px;top:88px;margin:0;font-size:14px;color:#434b57}.arrow{position:absolute;left:291px;top:204px;color:#aa732d;font-size:45px;font-weight:bold;letter-spacing:-6px}.footer{left:30px;right:30px;top:350px;padding-top:16px;border-top:1px solid #999;text-align:center;font-size:13px;color:#4c4c4c}</style>
  <header><span>aethon</span></header><img src="${image}"><h1>aethon</h1><p>Drag aethon to Applications.</p><div class="arrow">&#8594;</div><p class="footer">Local models. Your policy. Your choice.</p>`,
    660, 420, path.join(output, 'dmg-background.png'));
  app.quit();
}).catch(() => app.exit(1));
