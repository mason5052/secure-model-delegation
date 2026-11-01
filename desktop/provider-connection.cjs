'use strict';

const { spawn } = require('node:child_process');
const { privateEnvironment } = require('./lifecycle.cjs');

function nativeKey(helper, provider, icon) {
  return new Promise((resolve, reject) => {
    const child = spawn(helper, [provider, icon, String(process.pid)], {
      env: privateEnvironment(process.env), stdio: ['ignore', 'pipe', 'ignore'],
    });
    let chunks = [];
    let size = 0;
    child.stdout.on('data', chunk => {
      size += chunk.length;
      if (size > 4096) { child.kill(); chunks = []; return; }
      chunks.push(chunk);
    });
    child.on('error', () => reject(new Error('The native connection dialog could not open.')));
    child.on('close', code => {
      if (code === 2) return resolve(null);
      if (code !== 0 || size > 4096) return reject(new Error('The connection was not configured.'));
      resolve(Buffer.concat(chunks).toString('utf8'));
      chunks = [];
    });
  });
}

async function configureConnection(origin, input, prompt, request = fetch) {
  if (!input || !['openai', 'anthropic', 'remote'].includes(input.provider) ||
      typeof input.model !== 'string' || !input.model.trim() || input.model.length > 100 ||
      (input.base_url !== undefined && (typeof input.base_url !== 'string' || input.base_url.length > 1000))) {
    throw new Error('Choose a provider, model, and valid endpoint.');
  }
  let key = await prompt(input.provider);
  if (key === null) return { canceled: true };
  if (typeof key !== 'string' || !key || key.length > 1024) throw new Error('The connection was not configured.');
  try {
    const session = await request(origin + '/api/v1/session', { redirect: 'error', signal: AbortSignal.timeout(5000) });
    const { token } = await session.json();
    const cookie = session.headers.get('set-cookie')?.split(';')[0];
    if (!session.ok || !cookie || typeof token !== 'string') throw new Error('The local connection session could not start.');
    const body = { api_key: key, model: input.model.trim() };
    if (input.provider === 'remote') body.base_url = input.base_url;
    const response = await request(origin + '/api/v1/providers/' + input.provider, {
      method: 'PUT', redirect: 'error', signal: AbortSignal.timeout(5000),
      headers: { 'Content-Type': 'application/json', Origin: origin, Cookie: cookie, 'X-SMD-Token': token },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error('The connection settings were not accepted. Check the model, endpoint, and application status.');
    return { canceled: false, configured: true };
  } finally {
    key = null;
  }
}

module.exports = { nativeKey, configureConnection };
