import net from 'node:net';
import {randomUUID} from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

export async function prepareLaunch(profile) {
  const port = await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const value = server.address().port;
      server.close(error => error ? reject(error) : resolve(value));
    });
  });
  // Chrome treats --remote-debugging-port=0 as automation. Pass an explicit port,
  // matching the ordinary-browser login flow in browser_login.py.
  if (!Number.isInteger(port) || port <= 0) throw Error('无法分配本地登录端口。');
  const startFile = path.join(profile, 'quest-login-' + randomUUID() + '.html');
  await fs.writeFile(startFile, '<!doctype html><meta charset="utf-8"><title>学校登录准备中</title><p>正在打开学校登录页…</p>');
  const startUrl = pathToFileURL(startFile).href;
  return {
    port, startUrl,
    args: ['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=' + port,
      '--user-data-dir=' + profile, '--no-first-run', '--no-default-browser-check',
      '--window-size=1120,800', startUrl]
  };
}

export async function debuggerUrl(port) {
  const response = await fetch('http://127.0.0.1:' + port + '/json/version',
    {signal: AbortSignal.timeout(1000), redirect: 'error'});
  if (!response.ok) throw Error('登录窗口尚未就绪。');
  const value = (await response.json()).webSocketDebuggerUrl;
  const url = new URL(value);
  if (url.protocol !== 'ws:' || url.hostname !== '127.0.0.1' || Number(url.port) !== port ||
      !url.pathname.startsWith('/devtools/browser/')) throw Error('登录窗口调试地址不匹配。');
  return value;
}

export function failedPageMessage(state, elapsed) {
  if (!state || !['resm.lzjtu.edu.cn', 'authserver.lzjtu.edu.cn'].includes(state.host)) return null;
  // A 412 may be a transient initialization page; only fail persistent empty errors.
  if (state.empty && state.status >= 400 && elapsed >= 8000) {
    return `学校页面返回 HTTP ${state.status} 且页面空白，未导出会话。请关闭旧版窗口，重新下载并运行最新脚本；若仍失败，请反馈此状态码。`;
  }
  return null;
}
