'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const { profileDirectories } = require('../lifecycle.cjs');

const appData = path.join(os.tmpdir(), 'aethon-profile-test-appdata');
const first = path.join(os.tmpdir(), 'aethon-profile-test-one');
const second = path.join(os.tmpdir(), 'aethon-profile-test-two');

test('ordinary startup retains the existing desktop and legacy backend selection', () => {
  const exists = value => value === path.join(appData, 'SecureModelDelegation');
  const result = profileDirectories(appData, [], {}, exists);
  assert.equal(result.desktop, path.join(appData, 'aethon', 'desktop'));
  assert.equal(result.backend, path.join(appData, 'SecureModelDelegation'));
  assert.equal(result.isolated, false);
});

test('separate explicit profiles use separate lock and backend directories', () => {
  const a = profileDirectories(appData, [`--profile-root=${first}`]);
  const b = profileDirectories(appData, ['--profile-root', second]);
  const normal = profileDirectories(appData);
  assert.equal(a.desktop, path.join(first, 'desktop'));
  assert.equal(a.backend, path.join(first, 'backend'));
  assert.notEqual(a.desktop, b.desktop);
  assert.notEqual(a.backend, b.backend);
  assert.notEqual(a.desktop, normal.desktop);
  assert.notEqual(a.backend, normal.backend);
});

test('bundle-scoped environment profile works and explicit arguments take precedence', () => {
  assert.equal(profileDirectories(appData, [], { AETHON_PROFILE_ROOT: first }).root, first);
  assert.equal(profileDirectories(appData, [`--profile-root=${second}`], { AETHON_PROFILE_ROOT: first }).root, second);
});

test('invalid or ambiguous profile paths fail before normal profile selection', () => {
  for (const argv of [
    ['--profile-root'], ['--profile-root='], ['--profile-root=relative'],
    [`--profile-root=${path.parse(first).root}`],
    [`--profile-root=${first}\0hidden`],
    [`--profile-root=${first}`, `--profile-root=${second}`],
    ['--desktop-smoke', `--profile-root=${first}`],
  ]) assert.throws(() => profileDirectories(appData, argv));
  assert.throws(() => profileDirectories(appData, [], { AETHON_PROFILE_ROOT: '' }));
  assert.throws(() => profileDirectories(appData, [], { AETHON_PROFILE_ROOT: 'relative' }));
});
