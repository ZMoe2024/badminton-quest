import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {prepareLaunch, debuggerUrl, failedPageMessage} from './browser-launch.mjs';

test('ordinary Chrome startup uses a nonzero port and an isolated identifiable page', async t => {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'quest-launch-test-'));
  t.after(async () => {
    if(path.dirname(path.resolve(profile))===path.resolve(os.tmpdir())&&path.basename(profile).startsWith('quest-launch-test-'))await fs.rm(profile,{recursive:true,force:true});
  });
  const a = await prepareLaunch(profile);
  const b = await prepareLaunch(profile);
  assert.ok(a.port > 0 && a.port <= 65535);
  assert.ok(a.args.includes('--remote-debugging-port=' + a.port));
  assert.ok(a.args.includes('--remote-debugging-address=127.0.0.1'));
  assert.ok(a.args.includes('--user-data-dir=' + profile));
  assert.ok(!a.args.some(v => /--enable-automation|--headless|--remote-debugging-port=0$/.test(v)));
  assert.match(a.startUrl, /^file:\/\/\/.*quest-login-.*\.html$/);
  assert.notEqual(a.startUrl, b.startUrl);
});

test('debugger discovery rejects endpoints outside the owned local port', async () => {
  let endpoint;
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/json/version');
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({webSocketDebuggerUrl:endpoint}));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  try {
    endpoint = `ws://127.0.0.1:${port}/devtools/browser/test`;
    assert.equal(await debuggerUrl(port), endpoint);
    for (const bad of ['ws://example.com:9222/devtools/browser/test',
      `ws://127.0.0.1:${port + 1}/devtools/browser/test`,
      `ws://127.0.0.1:${port}/unexpected`]) {
      endpoint = bad;
      await assert.rejects(debuggerUrl(port), /不匹配/);
    }
  } finally { await new Promise(resolve => server.close(resolve)); }
});

test('only persistent blank school errors terminate login', () => {
  const state = {host:'resm.lzjtu.edu.cn', status:400, empty:true};
  assert.equal(failedPageMessage(state, 7999), null);
  assert.match(failedPageMessage(state, 8000), /HTTP 400/);
  assert.equal(failedPageMessage({...state, status:412}, 1000), null);
  assert.equal(failedPageMessage({...state, status:200}, 10000), null);
  assert.equal(failedPageMessage({...state, empty:false}, 10000), null);
  assert.equal(failedPageMessage({...state, host:'other.example'}, 10000), null);
});
