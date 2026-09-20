'use strict';
const originalFetch=window.fetch;
window.fetch=async(...args)=>{const response=await originalFetch(...args);if(response.status===401&&String(args[0]).startsWith('/api/')){location.assign('/login');throw Error('网站登录已过期');}return response;};
const renderLogin=window.LoginUI.render;
window.LoginUI.render=()=>renderLogin()
 .replaceAll('本机','当前账号的服务器空间')
 .replace('登录自己的学校账号','导入自己的学校会话')
 .replace('打开独立登录窗口，自己完成学校认证并进入预约首页。程序自动验证、加密保存会话，不读取日常浏览器的账号。','运行本地提取脚本，在它打开的学校窗口登录一次。脚本自动复制完整会话，再回到这里粘贴验证。')
 .replace('id="school-login"','id="school-login" hidden')
 .replace('学校认证彻底失效时需重新登录。登录完成不会自动启用任务或付款。','Cookie 或 Token 失效后需重新导入。仅导入预约网站 Cookie 不能保证自动续期或无人值守。')
 .replace(/<details>[\s\S]*?<\/details>/,`<h3>本地登录一次，复制结果即可</h3>
 <div class="manual-actions"><a class="button primary compact" href="/login-helper.zip?v=1.1" download="badminton-quest-login-helper.zip">下载登录提取脚本 v1.1</a><button class="button compact" id="show-helper-guide">Windows / Mac 教程</button></div>
 <ol class="session-steps">
 <li>下载并完整解压。Windows 双击 <strong>Start-Windows.cmd</strong>；Mac 按教程在终端运行。</li>
 <li>在脚本打开的<strong>独立学校窗口</strong>完成登录，等终端提示「已提取并复制完整会话」。</li>
 <li>回到这里粘贴完整 JSON，点击<strong>验证并保存</strong>。</li>
 </ol>
 <details id="helper-guide"><summary>使用教程：不需要浏览器扩展</summary>
 <p><strong>Windows 10/11：</strong>完整解压 ZIP，双击 <code>Start-Windows.cmd</code>；也可在解压目录的 PowerShell 输入 <code>.\\Start-Windows.cmd</code>。</p>
 <p><strong>macOS：</strong>打开「终端」，输入 <code>zsh </code>（末尾有空格），把解压后的 <code>Start-macOS.command</code> 拖进终端，回车。或在解压目录输入 <code>zsh ./Start-macOS.command</code>。</p>
 <p>电脑需已安装 Chrome 或 Edge。首次运行自动准备运行环境，不用自行安装 Python 或 Node.js。Mac 支持 Intel / Apple Silicon 启动包，尚需实机验证。</p>
 <p><strong>先启动脚本，再在它打开的窗口登录。</strong>它只读取本次独立登录，不读取日常浏览器资料。默认包含本次统一认证 Cookie 用于尝试续期；更多选项见 ZIP 内 README。</p>
 <p>正常结束会关闭独立窗口并清理临时资料，最长等待 10 分钟；Ctrl+C 可取消。复制失败时从终端手动复制完整 JSON。脚本不上传数据、不预约、不付款；只把结果粘贴到你信任的网站。</p>
 <p>提取成功不等于服务器验证成功，学校会话也可能过期。手机用户可先在电脑连接，再登录同一网站账号使用。</p></details>
 <label for="manual-json">粘贴脚本复制的会话 JSON</label><textarea id="manual-json" rows="5" autocomplete="off" spellcheck="false" placeholder='运行脚本、完成学校登录后，在这里粘贴完整 JSON'></textarea>
 <div class="manual-actions"><button class="button primary compact" id="manual-json-import">验证并保存</button><button class="button compact" id="manual-clear">清空凭据</button></div>
 <p id="manual-feedback" role="status"></p>
 <details class="manual-advanced"><summary>高级：逐项填写 / 导入文件</summary>
 <p>也可从同一次学校登录手动复制各项。</p>
 <label for="manual-complete-cookie">覆盖 JSON 的完整 Cookie（可选）</label><textarea id="manual-complete-cookie" rows="2" autocomplete="off" spellcheck="false" placeholder="仅手动补全时使用：学校网站 F12 → Network → 成功请求 → Request Headers → Cookie"></textarea>
 <label for="manual-cookie">Cookie</label><textarea id="manual-cookie" rows="3" autocomplete="off" spellcheck="false" placeholder="粘贴完整 Cookie 值"></textarea>
 <label for="manual-token">X-Access-Token</label><input id="manual-token" type="password" autocomplete="off" placeholder="Cookie 已含 token 时可留空">
 <label for="manual-user">currentUser</label><textarea id="manual-user" rows="2" autocomplete="off" spellcheck="false" placeholder="Application → Local Storage → 学校网站 → currentUser 的值"></textarea>
 <label for="manual-agent">User-Agent（可选，建议与原请求一致）</label><input id="manual-agent" autocomplete="off" placeholder="从同一请求的 Headers 复制">
 <div class="manual-actions"><button class="button compact" id="manual-import">验证逐项填写内容</button></div>
 <label for="manual-file">完整凭据 JSON 文件</label><input type="file" id="manual-file" accept="application/json,.json"><button class="button compact" id="manual-file-import">导入文件并验证</button><p>支持 cookie / cookies、token、currentUser、userAgent，以及可选的 ssoCookies。仅统一认证会话仍有效时才能尝试续期，不能保证永不过期。</p></details>`)
 .replace('不随发布包分享。独立登录窗口关闭后不保留浏览器资料。','仅供当前账号任务使用，验证失败不覆盖原会话。首次绑定后只接受同一学校身份。')
 .replace('不同电脑的任务不会自动同步。','不同设备登录同一网站账号即可查看。')
 .replace('你的本地冒险日志','你的冒险日志');
function clearManual(){for(const id of ['manual-json','manual-complete-cookie','manual-cookie','manual-token','manual-user','manual-agent','manual-file']){const el=$('#'+id);if(el)el.value='';}}
document.addEventListener('click',async event=>{
 const b=event.target.closest('button');if(!b)return;
 if(b.id==='manual-clear')clearManual();
 if(b.id==='show-helper-guide')$('#helper-guide').open=!$('#helper-guide').open;
 if(['manual-json-import','manual-import','manual-file-import'].includes(b.id)){
  const buttons=[$('#manual-json-import'),$('#manual-import'),$('#manual-file-import')];buttons.forEach(x=>x.disabled=true);
  const feedback=$('#manual-feedback');feedback.textContent='正在向学校验证，请稍候…';
  try{
   let credentials;
   if(b.id==='manual-json-import'){
    const text=$('#manual-json').value.trim();
    if(!text)throw Error('请先粘贴本地脚本复制的完整 JSON');
    if(new Blob([text]).size>90000)throw Error('内容过大，请只粘贴凭据 JSON');
    try{credentials=JSON.parse(text);}catch{throw Error('不是有效的 JSON，请复制完整提取结果，不要粘贴 JavaScript 代码');}
    if(!credentials||typeof credentials!=='object'||Array.isArray(credentials))throw Error('凭据应是包含 cookie、token、currentUser 的 JSON 对象');
    const fullCookie=$('#manual-complete-cookie').value.trim().replace(/^cookie:\s*/i,'');
    if(fullCookie){credentials.cookie=fullCookie;delete credentials.cookies;}
    const hasServerCookie=/(?:^|;\s*)evbSrBv8QGpBO=/.test(credentials.cookie||'')||
     (Array.isArray(credentials.cookies)&&credentials.cookies.some(c=>c?.name==='evbSrBv8QGpBO'&&c.value));
    if(!hasServerCookie)throw Error('会话中缺少 HttpOnly Cookie。请运行本地提取脚本，在独立窗口登录后复制完整结果。');
   }else if(b.id==='manual-file-import'){
    const file=$('#manual-file').files[0];if(!file)throw Error('请选择凭据 JSON 文件');
    if(file.size>90000)throw Error('文件过大，请只导入凭据 JSON');
    try{credentials=JSON.parse(await file.text());}catch{throw Error('文件不是有效的 JSON');}
   }else credentials={cookie:$('#manual-cookie').value,token:$('#manual-token').value,currentUser:$('#manual-user').value,userAgent:$('#manual-agent').value};
   await api('import',{credentials});clearManual();
   feedback.textContent='验证成功，已加密保存。可回到场地探索刷新。';
   await window.LoginUI.open();
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
 try{const d=await loadBootstrap();$('#web-username').textContent=d.websiteUser||'网站账号';}catch{}
});
