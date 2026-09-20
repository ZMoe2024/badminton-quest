'use strict';
const originalFetch=window.fetch;
window.fetch=async(...args)=>{const response=await originalFetch(...args);if(response.status===401&&String(args[0]).startsWith('/api/')){location.assign('/login');throw Error('网站登录已过期');}return response;};
const renderLogin=window.LoginUI.render;
window.LoginUI.render=()=>renderLogin()
 .replaceAll('本机','当前账号的服务器空间')
 .replace('登录自己的学校账号','导入自己的学校会话')
 .replace('打开独立登录窗口，自己完成学校认证并进入预约首页。程序自动验证、加密保存会话，不读取日常浏览器的账号。','先在学校预约网站登录，再填写下方凭据。验证通过后加密保存；不会自动预约或支付。')
 .replace('id="school-login"','id="school-login" hidden')
 .replace('学校认证彻底失效时需重新登录。登录完成不会自动启用任务或付款。','Cookie 或 Token 失效后需重新导入。仅导入预约网站 Cookie 不能保证自动续期或无人值守。')
 .replace(/<details>[\s\S]*?<\/details>/,`<h3>连接学校预约网站</h3>
 <p>在学校网站按 F12 → Network，选一条成功的请求，从 Request Headers 复制 Cookie 和 X-Access-Token 的值。</p>
 <label for="manual-cookie">Cookie</label><textarea id="manual-cookie" rows="3" autocomplete="off" spellcheck="false" placeholder="粘贴完整 Cookie 值"></textarea>
 <label for="manual-token">X-Access-Token</label><input id="manual-token" type="password" autocomplete="off" placeholder="Cookie 已含 token 时可留空">
 <label for="manual-user">currentUser</label><textarea id="manual-user" rows="2" autocomplete="off" spellcheck="false" placeholder="Application → Local Storage → 学校网站 → currentUser 的值"></textarea>
 <label for="manual-agent">User-Agent（可选，建议与原请求一致）</label><input id="manual-agent" autocomplete="off" placeholder="从同一请求的 Headers 复制">
 <div class="manual-actions"><button class="button primary compact" id="manual-import">验证并保存</button><button class="button compact" id="manual-clear">清空</button></div>
 <p id="manual-feedback" role="status"></p>
 <details><summary>已有完整凭据 JSON？</summary><input type="file" id="manual-file" accept="application/json,.json"><button class="button compact" id="manual-file-import">导入文件并验证</button><p>支持 cookie / cookies、token、currentUser、userAgent，以及可选的 ssoCookies。仅在统一认证会话仍有效时才能尝试续期。</p></details>`)
 .replace('不随发布包分享。独立登录窗口关闭后不保留浏览器资料。','仅供当前账号任务使用，验证失败不覆盖原会话。首次绑定后只接受同一学校身份。')
 .replace('不同电脑的任务不会自动同步。','不同设备登录同一网站账号即可查看。')
 .replace('你的本地冒险日志','你的冒险日志');
function clearManual(){for(const id of ['manual-cookie','manual-token','manual-user','manual-agent','manual-file']){const el=$('#'+id);if(el)el.value='';}}
document.addEventListener('click',async event=>{
 const b=event.target.closest('button');if(!b)return;
 if(b.id==='manual-clear')clearManual();
 if(['manual-import','manual-file-import'].includes(b.id)){
  const buttons=[$('#manual-import'),$('#manual-file-import')];buttons.forEach(x=>x.disabled=true);
  const feedback=$('#manual-feedback');feedback.textContent='正在向学校验证，请稍候…';
  try{
   let credentials;
   if(b.id==='manual-file-import'){
    const file=$('#manual-file').files[0];if(!file)throw Error('请选择凭据 JSON 文件');
    if(file.size>90000)throw Error('文件过大，请只导入凭据 JSON');
    try{credentials=JSON.parse(await file.text());}catch{throw Error('文件不是有效的 JSON');}
   }else credentials={cookie:$('#manual-cookie').value,token:$('#manual-token').value,currentUser:$('#manual-user').value,userAgent:$('#manual-agent').value};
   await api('import',{credentials});clearManual();
   feedback.textContent='验证成功，已加密保存。可回到场地探索刷新。';
   await sessionCheck();await window.LoginUI.open();
  }catch(exc){feedback.textContent=exc.message;}
  finally{buttons.forEach(x=>x.disabled=false);}
 }
 if(b.id==='web-logout'){
  b.disabled=true;fetch('/api/logout',{method:'POST',headers:{'X-Local-Token':token}}).then(r=>{if(!r.ok)throw Error('退出失败，请重试');location.assign('/login');}).catch(exc=>{toast(exc.message);b.disabled=false;});
 }
 if(b.id==='web-password')$('#password-dialog').showModal();
});
window.addEventListener('DOMContentLoaded',async()=>{
 document.body.classList.add('web-mode');
 $('.header-right').insertAdjacentHTML('afterbegin','<div class="web-account"><span id="web-username">网站账号</span><button id="web-password" title="修改网站密码">改密</button><button id="web-logout" title="退出网站；已启用任务继续执行">退出</button></div>');
 $('.statusbar span:nth-child(2)').textContent='关闭网页后，已启用任务继续运行';
 const status=$('#footer-status');const adjust=()=>{if(status.textContent==='本地运行 · 凭据保存在本机')status.textContent='网页版 · 个人数据独立保存';};
 new MutationObserver(adjust).observe(status,{childList:true});adjust();
 const note=$('.task-list-note');if(note)note.textContent='任务保存在你的账号中；停止任务不会取消已创建的预约。';
 const runtime=$('.runtime-note');if(runtime)runtime.textContent='服务器需保持运行；关闭手机或电脑网页不影响已启用任务。';
 document.body.insertAdjacentHTML('beforeend',`<dialog id="password-dialog" class="pixel-panel"><form id="password-form"><h2>修改网站密码</h2><p>修改后所有设备需重新登录，已启用任务继续运行。</p><label>原密码<input name="old" type="password" autocomplete="current-password" required maxlength="128"></label><label>新密码<input name="new" type="password" autocomplete="new-password" required minlength="10" maxlength="128"></label><p id="password-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button" id="password-close">取消</button><button class="button primary">保存并重新登录</button></div></form></dialog>`);
 $('#password-close').onclick=()=>$('#password-dialog').close();
 $('#password-form').onsubmit=async ev=>{ev.preventDefault();try{const r=await fetch('/api/password',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(Object.fromEntries(new FormData(ev.target)))});const d=await r.json();if(!r.ok)throw Error(d.error);location.assign('/login');}catch(exc){$('#password-error').textContent=exc.message;}};
 try{const d=await(await fetch('/api/bootstrap')).json();$('#web-username').textContent=d.websiteUser||'网站账号';}catch{}
});
