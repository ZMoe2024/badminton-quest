'use strict';
(() => {
 const A={mode:'scheduled_watch',candidates:[],draftId:null,monitorId:null,jobs:[],initialized:false,loading:false,polling:false,health:null};
 const states={draft:'尚未启用',waiting:'等待 / 候补',checking:'正在查询',submitting:'正在提交',paying:'正在付款',unknown:'预约待核查',payment_pending:'支付待核查',needs_login:'需要登录',paused:'已暂停',attention:'需要核实',booked:'已预约',paid:'已支付',expired:'已截止',cancelled:'已取消',unavailable:'没有空位'};
 const active=new Set(['waiting','checking','submitting','paying','unknown','payment_pending','needs_login','paused']);
 const short=s=>s?s.replace('T',' ').slice(5,19):'—';
 const beijing=()=>new Date(Date.now()+8*3600000).toISOString().slice(0,19);
 const courtName=id=>S.courts.find(c=>c.infoId===id)?.name||id;
 function setMode(mode){A.mode=mode;document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===mode);b.setAttribute('aria-pressed',b.dataset.mode===mode);});$('#auto-run').disabled=mode==='watch';$('#auto-until').closest('label').firstChild.textContent=mode==='scheduled'?'执行截止':'候补截止';preview();}
 function config(){return {mode:A.mode,candidates:[...A.candidates],date:$('#auto-date').value,start:$('#auto-start').value,end:$('#auto-end').value,runAt:A.mode==='watch'?beijing():$('#auto-run').value,until:$('#auto-until').value,interval:Number($('#auto-interval').value),pay:$('#auto-pay').checked,maxAmount:$('#auto-amount').value};}
 function candidates(){
  $('#auto-candidates').innerHTML=A.candidates.map((id,i)=>`<div class="candidate-row"><span class="handle">☰</span><b>${String(i+1).padStart(2,'0')}</b><i class="mini-court" aria-hidden="true"></i><strong>${e(courtName(id))}</strong><div class="candidate-controls"><button type="button" data-move="${i}" data-direction="-1" aria-label="${e(courtName(id))}上移" ${i===0?'disabled':''}>⌃</button><button type="button" data-move="${i}" data-direction="1" aria-label="${e(courtName(id))}下移" ${i===A.candidates.length-1?'disabled':''}>⌄</button><button type="button" data-remove="${i}" aria-label="移除${e(courtName(id))}">×</button></div></div>`).join('')||'<p class="task-empty">先添加一个目标场地</p>';
  $('#auto-court-add').innerHTML=S.courts.filter(c=>!A.candidates.includes(c.infoId)).map(c=>`<option value="${e(c.infoId)}">${e(c.name)}</option>`).join('');
  $('#auto-add').disabled=A.candidates.length>=6||!$('#auto-court-add').options.length;preview();
 }
 function initialize(){
  if(A.initialized||!S.courts.length)return;A.initialized=true;
  $('#auto-date').value=S.date;$('#auto-date').min=S.today;$('#auto-start').value=S.start||'10:00';$('#auto-end').value=S.end||'12:00';
  $('#auto-run').value=new Date(Date.now()+8*3600000+10*60000).toISOString().slice(0,19);
  $('#auto-until').value=S.date+'T'+($('#auto-start').value)+':00';
  A.candidates=[S.court?.infoId||S.courts[0].infoId];candidates();setMode('scheduled_watch');
 }
 function preview(){
  if(!A.initialized)return;
  const job=A.jobs.find(j=>j.id===A.monitorId),c=job?.config||config();
  const list=c.candidates.map(r=>typeof r==='string'?courtName(r):r.name);
  $('#preview-title').textContent=job?'任务进度':'任务预览';$('#auto-state').textContent=job?(states[job.state]||job.state):'尚未启用';
  $('#preview-playing').textContent=c.date?`${c.date.slice(5).replace('-','/')} ${c.start||'—'} — ${c.end||'—'}`:'请选择目标时间';
  $('#preview-courts').textContent=list.join(' → ')||'选择候选场地';$('#preview-courts').title=list.join(' → ');
  $('#preview-run').textContent='◷ '+(c.mode==='watch'?'启用后立即开始':short(c.runAt)+' 开始');
  $('#preview-until').textContent='◷ '+short(c.until)+' 截止';
  $('#auto-live').textContent=job?`${job.message}${job.lastCheckAt?' · 最近查询 '+short(job.lastCheckAt):''}${job.state==='waiting'?' · 下次 '+short(job.nextCheckAt):''}`:'任务未启用，不会自动提交。';
  $('#auto-cancel').hidden=!job||!active.has(job.state);$('#auto-cancel').disabled=!!job?.cancelRequested;
  const step=job?({waiting:0,checking:1,submitting:2,unknown:2,paying:3,payment_pending:3,booked:4,paid:4,expired:4,cancelled:4,unavailable:4}[job.state]??-1):-1;
  document.querySelectorAll('#auto-progress li').forEach((li,i)=>{li.classList.toggle('current',i===step);li.classList.toggle('done',i<step&&['booked','paid','paying','payment_pending'].includes(job?.state));});
 }
 function health(h){
  A.health=h;const el=$('#auto-health-state');const stale=h.state==='valid'&&(!h.checkedAt||Date.now()-new Date(h.checkedAt+'+08:00').getTime()>360000);el.className='health-state '+(stale?'unchecked':h.state);el.textContent=stale?'○ 上次有效，等待重新检查':(h.state==='valid'?'✓ ':'○ ')+h.message;
  $('#auto-health-time').textContent=short(h.checkedAt);$('#auto-renew-time').textContent=h.renewedAt?short(h.renewedAt):'尚无续期记录';
  $('#auto-health-state').title=h.renewalWarning||h.message;
 }
 function taskList(){
  $('#task-list-body').innerHTML=A.jobs.map(j=>`<article class="task-card"><header><h3>${e(j.config.date)} ${e(j.config.start)}–${e(j.config.end)}</h3><span class="badge">${e(states[j.state]||j.state)}</span></header><p>${e(j.config.candidates.map(c=>c.name).join(' → '))}</p><p>${e(j.message)}</p><p>${j.account?'账号 '+e(j.account)+' · ':''}${j.config.pay?'自动支付上限 ¥'+e(j.config.maxAmount):'不自动支付'} · 截止 ${e(short(j.config.until))}</p><div class="record-actions">${j.state==='draft'?`<button class="button compact" data-load-task="${j.id}">编辑草稿</button>`:`<button class="button compact" data-monitor-task="${j.id}">查看进度</button>`}${['needs_login','paused'].includes(j.state)&&!j.submittedAt?`<button class="button compact" data-resume-task="${j.id}">恢复任务</button>`:''}${active.has(j.state)||j.state==='draft'?`<button class="button compact" data-cancel-task="${j.id}" ${j.cancelRequested?'disabled':''}>${j.cancelRequested?'已请求停止':'停止任务'}</button>`:''}</div><details><summary>执行日志 · ${j.events.length} 条</summary><ul>${j.events.slice().reverse().map(x=>`<li>${e(short(x.at))} · ${e(x.message)}</li>`).join('')}</ul>${j.result?.submission?.reservation?.occupyId?`<p>预约编号：${e(j.result.submission.reservation.occupyId)}</p>`:''}${j.result?.order?.configuration?`<p>订单：${e(j.result.order.configuration.feeOrderId)} · ¥${e(j.result.order.configuration.expectedAmount)}</p>`:''}${j.recoveredRecord?`<p>找到的预约：${e(j.recoveredRecord.occupyId)} · ${e(j.recoveredRecord.recordUseStatus)}</p>`:''}</details></article>`).join('')||'<div class="task-empty">还没有任务。先设置目标，保存草稿或确认启用。</div>';
 }
 async function poll(){
  if(A.polling)return;A.polling=true;
  try{const d=await api('tasks');
   const prior=new Map(A.jobs.map(j=>[j.id,j.state]));A.jobs=d.jobs;health(d.health);$('#task-count').textContent=A.jobs.filter(j=>active.has(j.state)).length;
   for(const j of A.jobs){if(prior.has(j.id)&&prior.get(j.id)!==j.state&&['booked','paid','needs_login','attention','expired','paused'].includes(j.state))toast(j.message);}
   if(A.monitorId&&!A.jobs.some(j=>j.id===A.monitorId))A.monitorId=null;
   preview();if($('#task-list-dialog').open&&!$('#task-list-body details[open]'))taskList();
  }catch(err){$('#auto-live').textContent='后台连接失败：'+err.message;$('#auto-health-state').className='health-state error';$('#auto-health-state').textContent='○ 后台状态暂不可用';}
  finally{A.polling=false;}
 }
 async function operation(fn){if(A.loading)return;A.loading=true;$('#auto-enable').disabled=true;$('#auto-save').disabled=true;try{await fn();}catch(err){toast(err.message);$('#auto-save-status').textContent=err.message;}finally{A.loading=false;$('#auto-enable').disabled=false;$('#auto-save').disabled=false;}}
 async function save(){if(!$('#auto-form').reportValidity())throw Error('请先补全任务信息');const d=await api('task-save',{id:A.draftId,config:config()});A.draftId=d.id;$('#auto-save-status').textContent='草稿已保存';await poll();return d.id;}
 function confirmEnable(id,c){
  ask('启用这个自动预约任务？',`<p><strong>${e(c.date)} ${e(c.start)} — ${e(c.end)}</strong></p><p>${e(c.candidates.map(r=>typeof r==='string'?courtName(r):r.name).join(' → '))}</p><p>${c.mode==='watch'?'立即开始候补':e(short(c.runAt))+' 开始'}，${e(short(c.until))} 截止</p><p>${c.pay?'允许真实校园卡支付，最高 ¥'+e(c.maxAmount):'预约成功后保留待支付订单，不自动付款'}</p>`,'确认后后台会按这些条件自动预约。请保持电脑与后台运行；学校认证失效且无法续期时任务会暂停。',()=>operation(async()=>{await api('task-enable',{id,confirmed:true,requestId:crypto.randomUUID()});A.monitorId=id;A.draftId=null;$('#auto-save-status').textContent='任务已启用';await poll();toast('任务已启用，后台开始维护登录。');}));
 }
 function load(j){
  A.draftId=j.id;A.monitorId=null;const c=j.config;A.candidates=c.candidates.map(r=>r.infoId);
  $('#auto-date').value=c.date;$('#auto-start').value=c.start;$('#auto-end').value=c.end;$('#auto-run').value=c.runAt;$('#auto-until').value=c.until;$('#auto-interval').value=c.interval;$('#auto-pay').checked=c.pay;$('#auto-amount').value=c.maxAmount||'';$('#auto-amount').disabled=!c.pay;$('#auto-amount').required=c.pay;setMode(c.mode);candidates();$('#auto-save-status').textContent='正在编辑草稿';
 }
 function newTask(){A.draftId=null;A.monitorId=null;A.initialized=false;initialize();$('#auto-pay').checked=false;$('#auto-amount').value='';$('#auto-amount').disabled=true;$('#auto-amount').required=false;$('#auto-save-status').textContent='';preview();}
 async function cancel(id){await operation(async()=>{await api('task-cancel',{id});await poll();toast('已停止等待；已发出的预约或支付仍需核实。');});}
 $('#auto-form').addEventListener('submit',ev=>{ev.preventDefault();operation(async()=>{const id=await save();confirmEnable(id,config());});});
 $('#auto-form').addEventListener('input',()=>{if(A.monitorId){A.monitorId=null;}$('#auto-save-status').textContent='尚未保存的修改';preview();});
 $('#auto-pay').addEventListener('change',()=>{$('#auto-amount').disabled=!$('#auto-pay').checked;$('#auto-amount').required=$('#auto-pay').checked;preview();});
 document.addEventListener('click',ev=>{
  const b=ev.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.mode){A.monitorId=null;setMode(b.dataset.mode);return;}
  if(b.dataset.move!==undefined){const i=Number(b.dataset.move),n=i+Number(b.dataset.direction);[A.candidates[i],A.candidates[n]]=[A.candidates[n],A.candidates[i]];A.monitorId=null;candidates();return;}
  if(b.dataset.remove!==undefined){A.candidates.splice(Number(b.dataset.remove),1);A.monitorId=null;candidates();return;}
  if(b.dataset.loadTask){const j=A.jobs.find(j=>j.id===b.dataset.loadTask);if(j)load(j);$('#task-list-dialog').close();return;}
  if(b.dataset.monitorTask){A.monitorId=b.dataset.monitorTask;preview();$('#task-list-dialog').close();return;}
  if(b.dataset.cancelTask)return cancel(b.dataset.cancelTask);
  if(b.dataset.resumeTask){const j=A.jobs.find(j=>j.id===b.dataset.resumeTask);$('#task-list-dialog').close();if(j)confirmEnable(j.id,j.config);return;}
  switch(b.id){
   case 'auto-add':if($('#auto-court-add').value&&A.candidates.length<6){A.candidates.push($('#auto-court-add').value);A.monitorId=null;candidates();}break;
   case 'auto-save':operation(save);break;
   case 'auto-new':newTask();break;
   case 'auto-cancel':if(A.monitorId)cancel(A.monitorId);break;
   case 'task-list-open':taskList();$('#task-list-dialog').showModal();poll();break;
   case 'task-list-close':$('#task-list-dialog').close();break;
  }
 });
 window.AutomationUI={open(){initialize();poll();},poll};
 window.addEventListener('catalog-ready',()=>{initialize();poll();});
 setInterval(()=>{if(!document.hidden&&(S.view==='automation'||$('#task-list-dialog').open))poll();},5000);
})();
