'use strict';
const originalFetch=window.fetch;
window.fetch=async(...args)=>{const response=await originalFetch(...args);if(response.status===401&&String(args[0]).startsWith('/api/')){location.assign('/login');throw Error('网站登录已过期');}return response;};
const renderLogin=window.LoginUI.render;
window.LoginUI.render=()=>renderLogin()
 .replaceAll('本机','当前账号的服务器空间').replace('打开独立登录窗口，自己完成学校认证并进入预约首页。程序自动验证、加密保存会话，不读取日常浏览器的账号。','在下方远程窗口扫码或输入学校账号，完成后自动保存到你的独立账号空间。')
 .replace('不随发布包分享。独立登录窗口关闭后不保留浏览器资料。','仅供你的任务使用，登录结束会清理临时浏览器资料。')
 .replace(/<details>[\s\S]*?<\/details>/,'<h3>个人账号空间</h3><p>学校会话在服务器加密保存，不与其他使用者共享。首次绑定后，该网站账号只接受同一学校身份。</p>')
 .replace('不同电脑的任务不会自动同步。','不同设备登录同一网站账号即可查看。')
 .replace('你的本地冒险日志','你的冒险日志')+
 `<section class="remote-login pixel-panel" id="remote-login" hidden><header><div><h3>学校登录窗口</h3><p>由你操作学校页面。完成后自动关闭，不会自动预约或支付。</p></div><button class="button compact" id="remote-cancel">取消登录</button></header><p id="remote-hint" role="status">正在打开学校页面…</p><div class="remote-screen"><img id="school-screen" alt="学校登录页面，点击图片可操作；扫码请使用另一台设备" hidden draggable="false"></div><div class="remote-controls"><label for="school-text">输入到学校页面的当前选中框</label><div><input id="school-text" type="password" autocomplete="off" placeholder="先点图片中的输入框，再在此输入"><button id="remote-type" class="button compact">发送输入</button></div><div class="remote-keys"><button data-school-key="Tab">切换输入框</button><button data-school-key="Backspace">退格</button><button data-school-key="Enter">回车</button><button data-school-scroll="-1">向上滚动</button><button data-school-scroll="1">向下滚动</button></div></div></section>`;
window.addEventListener('school-login-state',event=>{
 const d=event.detail,panel=$('#remote-login');if(!panel)return;
 panel.hidden=!d.active;
 const loginMessage=(d.message||'').replace('点击登录学校账号，在独立窗口完成认证。','点击登录学校账号，在下方学校页面完成认证。').replace('正在打开独立登录窗口，请在窗口中使用自己的学校账号。','正在打开学校页面，请在下方使用自己的学校账号。');
 d.message=loginMessage;
 $('#remote-hint').textContent=loginMessage;
 const image=$('#school-screen');image.hidden=!d.screen;
 if(d.screen)image.src=d.screen;else image.removeAttribute('src');
});
const sendInput=async values=>{try{await api('login-input',values);}catch(exc){toast(exc.message);}};
document.addEventListener('click',event=>{
 const image=event.target.closest('#school-screen');
 if(image){const r=image.getBoundingClientRect();sendInput({kind:'click',x:(event.clientX-r.left)*1100/r.width,y:(event.clientY-r.top)*760/r.height});return;}
 const b=event.target.closest('button');if(!b)return;
 if(b.id==='remote-cancel')api('login-cancel').catch(exc=>toast(exc.message));
 if(b.id==='remote-type'){const input=$('#school-text');if(input.value){const text=input.value;input.value='';sendInput({kind:'text',text});}}
 if(b.dataset.schoolKey)sendInput({kind:'key',key:b.dataset.schoolKey});
 if(b.dataset.schoolScroll)sendInput({kind:'scroll',direction:Number(b.dataset.schoolScroll)});
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
