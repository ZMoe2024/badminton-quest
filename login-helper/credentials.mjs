const APP = 'https://resm.lzjtu.edu.cn';
function unwrap(value) {
  if (typeof value !== 'string') return value;
  try { value = decodeURIComponent(value); } catch {}
  if (value.startsWith('"')) { try { return JSON.parse(value); } catch {} }
  return value;
}
function json(value) {
  return JSON.parse(value.startsWith('{') ? value : Buffer.from(value, 'base64url').toString('utf8'));
}
function rows(cookies, host) {
  return cookies.filter(c => [host, 'lzjtu.edu.cn'].includes(c.domain.replace(/^\./, '')))
    .map(c => ({name:c.name, value:c.value, domain:c.domain, path:c.path, secure:c.secure, expires:c.expires ?? -1}));
}
export function collectCredentials(page, cookies, tokens = [], {now = Date.now(), includeSso = true} = {}) {
  if (page?.origin !== APP) return null;
  const appCookies = rows(cookies, 'resm.lzjtu.edu.cn');
  const currentUser = unwrap(page.currentUser || appCookies.find(c => c.name === 'currentUser')?.value);
  let user;
  try { user = typeof currentUser === 'string' ? json(currentUser) : currentUser; } catch {}
  if (!user || !user.username || !user.userId) return null;
  const token = [...tokens, page.token, ...appCookies.filter(c => c.name === 'token').map(c => c.value)].map(unwrap).find(value => {
    try {
      if (typeof value !== 'string' || value.split('.').length !== 3) return false;
      const claims = json(value.split('.')[1]);
      return String(claims.username) === String(user.username) && Number(claims.exp) > now / 1000 + 15;
    } catch { return false; }
  });
  if (!token || !['evbSrBv8QGpBO','evbSrBv8QGpBP'].every(name => appCookies.some(c => c.name === name && c.value))) return null;
  // The importer accepts an object and normalizes its encoding; do not carry browser-specific Base64 padding.
  const result = {cookies:appCookies, token, currentUser:user, userAgent:page.userAgent};
  if (includeSso) result.ssoCookies = rows(cookies, 'authserver.lzjtu.edu.cn');
  return result;
}

export const PAGE_SESSION = `(() => {
  if (location.origin !== 'https://resm.lzjtu.edu.cn') return {origin:location.origin};
  const data = {origin:location.origin, userAgent:navigator.userAgent};
  for (const key of ['token','currentUser']) {
    for (const name of ['localStorage','sessionStorage']) {
      try { data[key] ||= window[name].getItem(key); } catch {}
    }
  }
  return data;
})()`;
