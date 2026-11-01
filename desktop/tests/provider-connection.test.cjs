'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { configureConnection } = require('../provider-connection.cjs');

test('a canceled native key dialog sends no network request', async () => {
  let requests = 0;
  const result = await configureConnection('http://127.0.0.1:3000', { provider: 'openai', model: 'test' },
    async () => null, async () => { requests++; });
  assert.deepEqual(result, { canceled: true });
  assert.equal(requests, 0);
});

test('native key enters only the local request body and never the renderer result', async () => {
  const calls = [];
  const secret = 'synthetic-not-an-actual-api-key';
  const request = async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) return { ok: true, headers: new Headers({ 'set-cookie': 'smd_session=session; HttpOnly' }), json: async () => ({ token: 'session' }) };
    return { ok: true };
  };
  const result = await configureConnection('http://127.0.0.1:3000', { provider: 'remote', model: 'example', base_url: 'https://example.invalid/v1' }, async () => secret, request);
  assert.deepEqual(result, { canceled: false, configured: true });
  assert.equal(calls[1].url, 'http://127.0.0.1:3000/api/v1/providers/remote');
  assert.equal(JSON.parse(calls[1].options.body).api_key, secret);
  assert.equal(calls[1].options.headers.Cookie, 'smd_session=session');
  assert.equal(calls[1].options.headers['X-SMD-Token'], 'session');
  assert.equal(JSON.stringify(result).includes(secret), false);
});

test('unrecognized providers do not open a native dialog', async () => {
  let prompts = 0;
  await assert.rejects(configureConnection('http://127.0.0.1:3000', { provider: '../outside', model: 'test' }, async () => { prompts++; }), /Choose a provider/);
  assert.equal(prompts, 0);
});
