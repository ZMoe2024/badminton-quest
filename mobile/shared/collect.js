(() => {
  const origin = 'https://resm.lzjtu.edu.cn';
  if (location.origin !== origin) return {ok:false,message:'请完成学校登录，并返回预约首页。'};
  const unwrap = input => {
    if (typeof input !== 'string') return input;
    let value = input;
    try { value = decodeURIComponent(value); } catch {}
    try { if (value.startsWith('"')) value = JSON.parse(value); } catch {}
    return value;
  };
  const decode = value => {
    const text = value.replace(/-/g,'+').replace(/_/g,'/');
    return new TextDecoder().decode(Uint8Array.from(atob(text+'='.repeat((4-text.length%4)%4)),c=>c.charCodeAt(0)));
  };
  const cookies = {};
  for (const part of document.cookie.split(';')) {
    const split = part.indexOf('=');
    if (split > 0) cookies[part.slice(0,split).trim()] = unwrap(part.slice(split+1));
  }
  const read = key => {
    for (const store of [localStorage,sessionStorage]) {
      try { const value=store.getItem(key);if(value)return unwrap(value); } catch {}
    }
    return cookies[key];
  };
  try {
    let user=read('currentUser');
    if(typeof user==='string')user=JSON.parse(user.startsWith('{')?user:decode(user));
    if(!user?.username||!user?.userId)throw Error('missing user');
    const candidates=[];
    for(const store of [localStorage,sessionStorage])try{candidates.push(unwrap(store.getItem('token')));}catch{}
    candidates.push(cookies.token);
    const token=candidates.find(value=>{
      try {
        if(typeof value!=='string'||value.split('.').length!==3)return false;
        const claims=JSON.parse(decode(value.split('.')[1]));
        return String(claims.username)===String(user.username)&&Number(claims.exp)>Date.now()/1000+30;
      }catch{return false;}
    });
    if(!token)return {ok:false,message:'登录尚未完成或已过期，请进入预约首页后重试。'};
    return {ok:true,origin,token,currentUser:user,userAgent:navigator.userAgent};
  }catch{return {ok:false,message:'还未读取到学校身份，请完成认证后再点完成登录。'};}
})()
