'use strict';
window.LoginUI = (() => {
 let timer=null, polling=false, busy=false, lastSuccess=false;
 const render=()=>`<div class="settings-grid">
 <section class="settings-card"><h3>登录自己的学校账号</h3><p>打开独立登录窗口，自己完成学校认证并进入预约首页。程序自动验证、加密保存会话，不读取日常浏览器的账号。</p>
 <div class="login-actions"><button class="button primary compact" id="school-login">登录学校账号 ↗</button><button class="button compact" id="cancel-school-login" hidden>取消登录</button></div>
 <p id="school-login-status" role="status">正在读取登录状态…</p><p id="school-login-account"></p>
 <div class="login-secondary-actions"><button class="button compact" id="verify-login">检查登录状态</button><button class="button compact" id="renew-login">尝试续期</button></div><p id="login-feedback"></p>
 <p class="login-note">学校认证彻底失效时需重新登录。登录完成不会自动启用任务或付款。</p></section>
 <section class="settings-card"><h3>预约联系电话</h3><p>填写你本人的联系电话，预约表单会使用这里的值。身份由当前登录账号决定。</p>
 <label for="booking-phone">联系电话</label><input type="tel" id="booking-phone" inputmode="tel" autocomplete="tel" maxlength="16" placeholder="填写联系电话">
 <button class="button compact" id="save-booking-phone">保存联系电话</button><p id="booking-phone-status" role="status"></p>
 <h3>实时场地目录</h3><p>登录后从学校网站更新羽毛球场馆目录，空闲时段仍需实时查询。</p><button class="button compact" id="refresh-catalog">更新场地目录</button></section>
 <section class="settings-card"><details><summary>高级选项：手动导入会话</summary><p>已有凭据 JSON 时可手动导入，一般使用上方登录按钮即可。</p>
 <label for="session-file">凭据文件</label><input type="file" id="session-file" accept="application/json,.json"><button class="button compact" id="import-login">导入并验证</button></details>
 <p>凭据只加密保存在本机，不随发布包分享。独立登录窗口关闭后不保留浏览器资料。</p></section>
 <section class="settings-card"><h3>你的本地冒险日志</h3><p>预约、订单与支付结果保存在本机。结果未知时请先查询原订单，不要删除记录重试。</p><p>取消和退款请到学校网站操作；不同电脑的任务不会自动同步。</p></section></div>`;
 function display(d){
  window.dispatchEvent(new CustomEvent('school-login-state',{detail:d}));
  if(!$('#school-login-status'))return;
  $('#school-login-status').textContent=d.message;
  $('#school-login-status').dataset.state=d.state;
  $('#school-login').disabled=d.active||busy;
  $('#cancel-school-login').hidden=!d.active;
  $('#cancel-school-login').disabled=d.state==='cancelling';
  $('#school-login-account').textContent=d.account?`当前账号 ${d.account} · ${d.ssoAvailable?'已获取学校认证会话，可尝试自动续期':'未获取学校认证会话，到期后需重新登录'}`:'';
  if(d.state==='success'&&!lastSuccess){
   lastSuccess=true;
   $('#session-pill').textContent=`● ${d.account} 已连接`;
   $('#session-pill').style.color='var(--green)';
   S.live=null;S.received=0;resetPrice();updateButtons();
   message('学校账号已连接','填写联系电话后，回到场地探索刷新实时状态。');
  }else if(d.state!=='success')lastSuccess=false;
 }
 async function poll(){
  if(S.view!=='settings'||polling)return;
  polling=true;
  try{display(await api('login-status'));}
  catch(err){if($('#school-login-status'))$('#school-login-status').textContent=err.message;}
  finally{polling=false;}
 }
 async function open(){
  clearInterval(timer);
  const d=await api('profile');
  if($('#booking-phone'))$('#booking-phone').value=d.phone||'';
  await poll();
  timer=setInterval(poll,1500);
 }
 document.addEventListener('click',async ev=>{
  const button=ev.target.closest('button');if(!button||button.disabled)return;
  if(button.id==='school-login'||button.id==='cancel-school-login'){
   busy=true;button.disabled=true;
   try{display(await api(button.id==='school-login'?'login-start':'login-cancel'));}
   catch(err){toast(err.message);}
   finally{busy=false;await poll();}
  }
  if(button.id==='save-booking-phone'){
   button.disabled=true;
   try{await api('save-profile',{phone:$('#booking-phone').value});$('#booking-phone-status').textContent='联系电话已保存在本机。';}
   catch(err){$('#booking-phone-status').textContent=err.message;}
   finally{button.disabled=false;}
  }
 });
 return {render,open};
})();
