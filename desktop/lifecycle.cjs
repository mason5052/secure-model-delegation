'use strict';

const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');

function dataDirectory(appData, exists = fs.existsSync) {
  const current = path.join(appData, 'aethon');
  const legacy = path.join(appData, 'SecureModelDelegation');
  const currentHasData = ['application.sqlite3', 'runtime-state.json'].some(name => exists(path.join(current, name)));
  return exists(legacy) && !currentHasData ? legacy : current;
}

function privateEnvironment(inherited, overrides = {}) {
  const permitted = new Set(['PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL',
    'SYSTEMROOT', 'WINDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR']);
  const result = {};
  for (const [key, value] of Object.entries(inherited)) {
    if (permitted.has(key) && typeof value === 'string') result[key] = value;
  }
  return { ...result, ...overrides, PYTHONUNBUFFERED: '1', NO_PROXY: '127.0.0.1,localhost,::1' };
}

class Backend extends EventEmitter {
  constructor(command, args, options = {}) {
    super();
    this.command = command;
    this.args = args;
    this.options = options;
    this.child = null;
    this.stopping = false;
    this.pendingStop = null;
  }

  start(timeoutMs = 180000) {
    return new Promise((resolve, reject) => {
      let settled = false;
      let buffered = '';
      const finish = (error, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        error ? reject(error) : resolve(value);
      };
      const timer = setTimeout(() => {
        finish(new Error('The local service did not finish starting. Quit and try again.'));
        void this.stop();
      }, timeoutMs);
      this.child = spawn(this.command, this.args, {
        ...this.options, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      });
      this.child.on('error', () => finish(new Error('The bundled local service could not start.')));
      this.child.stdout.setEncoding('utf8');
      this.child.stdout.on('data', chunk => {
        buffered += chunk;
        if (buffered.length > 65536) {
          finish(new Error('The local service returned an invalid startup response.'));
          void this.stop();
          return;
        }
        const lines = buffered.split('\n');
        buffered = lines.pop();
        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.event === 'ready' && event.host === '127.0.0.1' &&
                Number.isInteger(event.port) && event.port > 0 && event.port < 65536) {
              finish(null, `http://127.0.0.1:${event.port}`);
              this.childPids = Array.isArray(event.child_pids) ? event.child_pids.filter(pid => Number.isInteger(pid) && pid > 0) : [];
            }
          } catch { /* Only the typed readiness record is consumed. */ }
        }
      });
      // Never copy server output or provider errors into desktop logs or the renderer.
      this.child.stderr.resume();
      this.child.on('exit', (code, signal) => {
        finish(new Error('The local service stopped before it was ready.'));
        if (!this.stopping) this.emit('unexpected-exit', { code, signal });
      });
    });
  }

  stop(timeoutMs = 25000) {
    if (this.pendingStop) return this.pendingStop;
    this.stopping = true;
    this.pendingStop = new Promise(resolve => {
      const child = this.child;
      if (!child || child.exitCode !== null || child.signalCode !== null) return resolve();
      let killTimer;
      const timer = setTimeout(() => {
        child.kill('SIGTERM');
        killTimer = setTimeout(() => { child.kill('SIGKILL'); }, 5000);
        killTimer.unref();
      }, timeoutMs);
      child.once('exit', () => { clearTimeout(timer); clearTimeout(killTimer); resolve(); });
      if (child.stdin.writable) child.stdin.end('{"command":"shutdown"}\n');
    });
    return this.pendingStop;
  }
}

module.exports = { Backend, privateEnvironment, dataDirectory };
