'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { Backend, privateEnvironment, dataDirectory } = require('../lifecycle.cjs');

test('brand rename retains legacy policies even after a new desktop profile exists', () => {
  const entries = new Set(['/data/SecureModelDelegation', '/data/aethon', '/data/aethon/desktop']);
  assert.equal(dataDirectory('/data', name => entries.has(name)), '/data/SecureModelDelegation');
  entries.add('/data/aethon/application.sqlite3');
  assert.equal(dataDirectory('/data', name => entries.has(name)), '/data/aethon');
  assert.equal(dataDirectory('/fresh', () => false), '/fresh/aethon');
});

test('provider keys and shell initialization variables are not inherited', () => {
  const env = privateEnvironment({ PATH: '/bin', HOME: '/tmp/person', OPENAI_API_KEY: 'private',
    ANTHROPIC_API_KEY: 'private', AWS_SECRET_ACCESS_KEY: 'private', NODE_OPTIONS: '--inspect',
    PYTHONPATH: '/untrusted', OLLAMA_HOST: 'https://remote.example', SMD_ATTACK: 'no' }, { SMD_OPENCODE_BINARY: '/trusted/engine' });
  assert.equal(env.PATH, '/bin');
  assert.equal(env.SMD_OPENCODE_BINARY, '/trusted/engine');
  for (const key of ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'NODE_OPTIONS', 'PYTHONPATH', 'OLLAMA_HOST', 'SMD_ATTACK']) assert.equal(env[key], undefined);
});

test('readiness consumes split records and shutdown uses the owned stdin pipe', async () => {
  const code = `process.stdout.write('{"event":"ready","host":"127.0.0.1",');
    setTimeout(() => process.stdout.write('"port":43001}\\n'), 20);
    process.stdin.once('data', data => process.exit(JSON.parse(data).command === 'shutdown' ? 0 : 3));`;
  const backend = new Backend(process.execPath, ['-e', code], { env: privateEnvironment(process.env) });
  assert.equal(await backend.start(3000), 'http://127.0.0.1:43001');
  await backend.stop(1000);
  assert.equal(backend.child.exitCode, 0);
});

test('a foreign ready host is not accepted and an exited service fails', async () => {
  const backend = new Backend(process.execPath, ['-e', 'console.log(JSON.stringify({event:"ready",host:"0.0.0.0",port:43001}))']);
  backend.on('unexpected-exit', () => {});
  await assert.rejects(backend.start(3000), /stopped before/);
  await backend.stop();
});

test('quit escalates only the owned child when it ignores the control pipe', async () => {
  const code = 'console.log(JSON.stringify({event:"ready",host:"127.0.0.1",port:43001})); setInterval(()=>{},1000)';
  const backend = new Backend(process.execPath, ['-e', code]);
  await backend.start(3000);
  await backend.stop(30);
  assert.equal(backend.child.signalCode, 'SIGTERM');
});
