'use strict';
(()=>{
 let snapshot={canManage:false,items:[]},editing=null,mandatory=false;
 // Reading is acknowledged for this page visit only. A new visit shows active
 // notices again; polling an unchanged revision must not continually reopen it.
 const acknowledged=new Set(),revision=n=>`${n.id}:${n.updated}`;
 const published=()=>snapshot.items.filter(n=>n.active!==false);
 function promptUnread(){
  const dialog=$('#notice-dialog');if(!dialog)return;
  const pending=published().some(n=>!acknowledged.has(revision(n)));
  if(!pending){if(mandatory){mandatory=false;render();}return;}
  // Do not cover a booking/payment confirmation or discard an administrator's draft.
  if([...document.querySelectorAll('dialog[open]')].some(d=>d!==dialog)||!$('#notice-form').hidden)return;
  mandatory=true;render();
  if(!dialog.open){dialog.showModal();dialog.scrollTop=0;}
 }
 async function load(){
  const r=await fetch('/api/notices');if(!r.ok)throw Error('公告暂未加载，请重试');
  snapshot=await r.json();const latest=published()[0];
  const banner=$('#notice-banner');banner.hidden=!latest;
  if(latest){banner.textContent='公告 · '+latest.title;banner.title=latest.title;}
  $('#notice-open').textContent='公告'+(published().length?' · '+published().length:'');
  promptUnread();
 }
 function render(){
  $('#notice-manage').hidden=!snapshot.canManage||mandatory;
  $('#notice-close').hidden=mandatory;
  $('#notice-refresh').hidden=mandatory;
  $('#notice-required').hidden=!mandatory;
  $('#notice-list').innerHTML=(mandatory?published():snapshot.items).map(n=>`<article class="notice-card"><header><h3>${n.pinned?'📌 ':''}${e(n.title)}</h3>${snapshot.canManage&&!mandatory?`<button class="button compact" data-notice-edit="${e(n.id)}">编辑</button>`:''}</header><p class="notice-meta">${n.active===false?'草稿 / 已下架 · ':''}${new Date(n.updated*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}</p><div class="notice-copy">${e(n.body)}</div></article>`).join('')||'<div class="empty">暂无公告。</div>';
 }
 async function show(){
  if(!$('#notice-dialog').open)$('#notice-dialog').showModal();
  $('#notice-error').textContent='';
  try{await load();render();}catch(err){$('#notice-error').textContent=err.message;}
 }
 function edit(item){
  editing=item;const f=$('#notice-form');f.hidden=false;
  f.elements.title.value=item?.title||'';f.elements.body.value=item?.body||'';
  f.elements.pinned.checked=!!item?.pinned;f.elements.active.checked=item?.active!==false;
  $('#notice-editor-label').textContent=item?'编辑公告':'新公告';f.scrollIntoView({block:'nearest'});f.elements.title.focus();
 }
 window.addEventListener('DOMContentLoaded',()=>{
  $('.web-account').insertAdjacentHTML('beforeend','<button id="notice-open">公告</button>');
  $('.welcome>div').insertAdjacentHTML('beforeend','<button id="notice-banner" class="notice-banner" hidden></button>');
  document.body.insertAdjacentHTML('beforeend',`<dialog id="notice-dialog" class="pixel-panel"><header class="notice-heading"><div><p class="eyebrow">TRAINER BULLETIN</p><h2>道馆公告板</h2></div><button class="button compact" id="notice-close" aria-label="关闭公告">关闭</button></header><div class="notice-tools"><button class="button compact" id="notice-refresh">刷新</button><button class="button primary compact" id="notice-manage" hidden>发布新公告</button></div><p id="notice-error" role="alert"></p><form id="notice-form" hidden><h3 id="notice-editor-label">新公告</h3><label>标题<input name="title" maxlength="80" required></label><label>正文（纯文本）<textarea name="body" rows="6" maxlength="4000" required></textarea></label><div class="notice-options"><label><input name="pinned" type="checkbox">置顶</label><label><input name="active" type="checkbox">对用户发布（取消勾选即下架）</label></div><div class="notice-tools"><button class="button primary" type="submit">保存公告</button><button class="button" type="button" id="notice-edit-cancel">取消编辑</button></div></form><div id="notice-list"></div></dialog>`);
  $('#notice-dialog').insertAdjacentHTML('beforeend','<footer id="notice-required" hidden><p>请阅读以上公告，确认后继续使用。</p><button class="button primary" id="notice-acknowledge">我已阅读，继续使用</button></footer>');
  $('#notice-dialog').addEventListener('cancel',ev=>{if(mandatory)ev.preventDefault();});
  $('#notice-form').addEventListener('submit',async ev=>{
   ev.preventDefault();const f=ev.target,b=f.querySelector('[type="submit"]');b.disabled=true;$('#notice-error').textContent='';
   try{
    const data={title:f.elements.title.value,body:f.elements.body.value,pinned:f.elements.pinned.checked,active:f.elements.active.checked};
    if(editing){data.id=editing.id;data.version=editing.version;}
    const r=await fetch('/api/notices',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(data)}),result=await r.json();
    if(!r.ok)throw Error(result.error||'保存失败');f.hidden=true;editing=null;await load();render();toast(data.active?'公告已发布':'公告已保存为草稿 / 下架');
   }catch(err){$('#notice-error').textContent=err.message;}finally{b.disabled=false;}
  });
  load().catch(()=>{$('#notice-open').textContent='公告 · 重试';});
 });
 document.addEventListener('click',ev=>{
  const b=ev.target.closest('button');if(!b||b.disabled)return;
  if(['notice-open','notice-banner','notice-refresh'].includes(b.id))return show();
  if(b.id==='notice-acknowledge'){
   published().forEach(n=>acknowledged.add(revision(n)));mandatory=false;render();$('#notice-dialog').close();return;
  }
  if(b.id==='notice-close'&&!mandatory)return $('#notice-dialog').close();
  if(b.id==='notice-manage')return edit(null);
  if(b.id==='notice-edit-cancel'){$('#notice-form').hidden=true;editing=null;}
  if(b.dataset.noticeEdit)edit(snapshot.items.find(n=>n.id===b.dataset.noticeEdit));
 });
 document.addEventListener('close',()=>queueMicrotask(promptUnread),true);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!$('#notice-dialog')?.open)load().catch(()=>{});});
 setInterval(()=>{if(!document.hidden&&!$('#notice-dialog')?.open)load().catch(()=>{});},120000);
})();
