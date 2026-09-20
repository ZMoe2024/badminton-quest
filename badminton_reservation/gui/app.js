'use strict';
const $ = s => document.querySelector(s);
const token = $('meta[name="local-token"]').content;
const S = {courts:[], group:'main', court:null, date:'', today:'', start:'', end:'', live:null, liveError:false, busy:false, view:'explore', epoch:0, received:0, confirming:null};
const escapeHTML = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHTML;
const dateLabel = d => {const x=new Date(d+'T12:00:00+08:00');return `${d}（周${'日一二三四五六'[x.getUTCDay()]}）`;};
const dayOffset = (d,n) => {const x=new Date(d+'T12:00:00Z');x.setUTCDate(x.getUTCDate()+n);return x.toISOString().slice(0,10);};
const cfg = () => ({venue:S.court?.infoId,date:S.date,start:S.start,end:S.end});
const visibleCourts = () => S.courts.filter(c=>c.group===S.group);
function message(title,text){$('#dialogue-title').textContent=title;$('#dialogue-text').textContent=text;}
function resetPrice(){$('#price').textContent='查单后显示';$('#price-unit').textContent='—';}
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,4800);}
function markBusy(value,label='正在连接学校预约网站…'){
 S.busy=value;document.body.classList.toggle('busy',value);
 $('#footer-status').textContent=value?label:'本地运行 · 凭据保存在本机';
 $('#refresh').disabled=value;$('#reload-secondary').disabled=value;
 document.querySelectorAll('.nav-item,.gym-tabs button,#date-input,#court-select,#pay-toggle,#save-config,.date-chip').forEach(el=>el.disabled=value);
 updateButtons();
}
async function api(action,values={}){
 const response=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({action,...values})});
 const data=await response.json();if(!response.ok||data.error)throw new Error(data.error||'请求失败');return data;
}
async function task(label,fn){if(S.busy){toast('当前操作尚未完成，请稍候。');return;}markBusy(true,label);try{return await fn();}catch(err){toast(err.message);message('道馆传来了消息',err.message);if(S.view!=='explore'&&$('#secondary-content').textContent.includes('正在打开训练家手册'))$('#secondary-content').innerHTML=`<div class="empty">${e(err.message)}<br>点击右上角刷新重试。</div>`;}finally{markBusy(false);}}
function fresh(){return S.live && S.live.date===S.date && Date.now()-S.received<90000;}
function currentData(){return S.live?.courts.find(c=>c.infoId===S.court?.infoId);}
function selectedSlot(){return currentData()?.slots.find(s=>s.start===S.start&&s.end===S.end);}
function updateButtons(){const usable=!S.busy&&fresh()&&selectedSlot()?.available;$('#book').disabled=!usable;$('#check').disabled=!usable;}
function art(){document.querySelectorAll('[data-crop]').forEach(el=>{const[x,y,w,h]=el.dataset.crop.split(',').map(Number);const img=document.createElement('img');img.src='/assets/concept.png';img.alt='';img.style.width=(1586/w*100)+'%';img.style.left=(-x/w*100)+'%';img.style.top='0';img.style.transform=`translateY(${-y/992*100}%)`;el.append(img);});}
function renderDates(){
 $('#date-input').value=S.date;$('#date-input').min=S.today;
 let start=S.date<S.today?S.today:S.date;
 if(S.date<=dayOffset(S.today,4))start=S.today;
 $('#date-strip').innerHTML=Array.from({length:5},(_,i)=>{const d=dayOffset(start,i);const day='日一二三四五六'[new Date(d+'T12:00:00Z').getUTCDay()];return `<button class="date-chip ${d===S.date?'active':''}" data-date="${d}" aria-pressed="${d===S.date}" aria-label="${d} 周${day}"><small>周${day}</small><strong>${Number(d.slice(-2))}</strong></button>`;}).join('');
}
function renderSelection(){
 if(fresh()&&!selectedSlot()){
  const slots=currentData()?.slots||[];const next=slots.find(s=>s.available)||slots[0];
  S.start=next?.start||'';S.end=next?.end||'';
 }
 const rows=visibleCourts();
 $('#court-select').innerHTML=rows.map(c=>`<option value="${e(c.infoId)}" ${c.infoId===S.court?.infoId?'selected':''}>${e(c.name)}</option>`).join('');
 $('#selected-name').textContent=S.court?.name||'请选择场地';
 $('#selected-location').textContent=S.group==='main'?'北校区 · 综合馆（主馆）':S.group==='annex'?'北校区 · 副馆二楼':'天佑体育馆';
 $('#court-count').textContent=`${rows.length} 块场地`;
 $('#map-caption').textContent=`${S.date} · ${S.start?S.start+'–'+S.end:'选择时段查看状态'}`;
 renderMap();renderSlots();renderDates();updateButtons();
}
function renderMap(){
 const rows=visibleCourts();const cols=rows.length>7?7:Math.ceil(rows.length/2);
 $('#map-courts').style.gridTemplateColumns=`repeat(${cols}, minmax(0, 1fr))`;
 $('#map-courts').style.setProperty('--mobile-map-rows',Math.max(1,Math.ceil(rows.length/4)));
 $('#map-courts').innerHTML=rows.map((c,i)=>{
  const live=S.live?.courts.find(x=>x.infoId===c.infoId);const slot=live?.slots.find(x=>x.start===S.start&&x.end===S.end);
  const state=fresh()&&slot?slot.state:'unknown';
  const label=S.liveError||live?.error?'查询失败':fresh()&&slot?slot.label:live&&!fresh()?'需刷新':fresh()&&live?(S.start?'无此时段':'无可选时段'):'查询中';
  return `<button class="court ${state} ${c.infoId===S.court?.infoId?'selected':''}" data-court="${e(c.infoId)}" aria-label="${e(c.name)}，${e(label)}" aria-pressed="${c.infoId===S.court?.infoId}"><span class="selector">▼</span><span class="court-status">${e(label)}</span><span class="court-number">${String(i+1).padStart(2,'0')}</span></button>`;
 }).join('');
}
function renderSlots(){
 const d=currentData();
 if(!d){$('#slots').innerHTML='<div class="empty">正在读取网站时段…<br>未查询的场地不会标为可预约</div>';$('#slot-source').textContent='等待实时查询';return;}
 if(d.error){$('#slots').innerHTML=`<div class="empty">${e(d.error)}<br>点击「刷新状态」重试</div>`;$('#slot-source').textContent='查询失败';return;}
 if(!d.slots.length){$('#slots').innerHTML='<div class="empty">网站未返回当天可选时段</div>';$('#slot-source').textContent='没有配置时段';return;}
 $('#slot-source').textContent=fresh()?'来自学校网站':'数据已过期';
 $('#slots').innerHTML=d.slots.map(s=>`<button class="slot ${s.state} ${s.start===S.start&&s.end===S.end?'selected':''}" data-start="${e(s.start)}" data-end="${e(s.end)}" ${!fresh()?'disabled':''} aria-pressed="${s.start===S.start&&s.end===S.end}"><strong>${e(s.start)} – ${e(s.end)}</strong><small>${fresh()?e(s.label):'需刷新'}</small></button>`).join('');
}
async function refreshLive(){
 const epoch=++S.epoch;S.live=null;S.liveError=false;S.received=0;$('#sync-time').textContent='正在实时查询…';renderMap();renderSlots();updateButtons();
 try{
  const d=await api('availability',{group:S.group,date:S.date});if(epoch!==S.epoch)return;
  S.live=d;S.received=Date.now();
  const time=new Date(d.fetchedAt).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
  const errors=d.courts.filter(c=>c.error).length;
  $('#sync-time').textContent=`${errors?'部分查询失败 · ':''}${time} 更新`;
  message(errors?'部分道馆还没有回应':'准备好了吗，训练家？',errors?'查询失败的场地会显示未知，请刷新后再选择。':`${dateLabel(S.date)}，选择你喜欢的场地和时段。空闲时段仍须通过账号额度校验。`);
  renderSelection();
 }catch(err){S.live=null;S.liveError=true;$('#sync-time').textContent='查询失败 · 状态未知';$('#slot-source').textContent='查询失败';$('#slots').innerHTML=`<div class="empty">${e(err.message)}<br>没有使用旧的空闲状态</div>`;renderMap();throw err;}
}
async function switchGroup(group){if(S.busy)return;resetPrice();S.group=group;S.court=visibleCourts()[0];document.querySelectorAll('[data-group]').forEach(b=>{b.classList.toggle('active',b.dataset.group===group);b.setAttribute('aria-selected',b.dataset.group===group);});renderSelection();await task('正在查询场馆实时状态…',refreshLive);}
async function switchDate(date){if(S.busy||!date)return;resetPrice();S.date=date;S.live=null;renderSelection();await task('正在查询所选日期…',refreshLive);}
async function sessionCheck(renew=false){const d=await api(renew?'renew':'session');$('#session-pill').textContent=`● ${d.account} 已连接`;$('#session-pill').style.color='var(--green)';return d;}
function ask(title,details,note,onSubmit){S.confirming=onSubmit;$('#confirm-dialog').returnValue='cancel';$('#confirm-title').textContent=title;$('#confirm-details').innerHTML=details;$('#confirm-note').textContent=note;$('#confirm-dialog').showModal();}
function showResult(title,html){$('#result-title').textContent=title;$('#result-content').innerHTML=html;$('#result-dialog').showModal();}
function bookingResult(result){
 const s=result.submission||{},p=result.payment,o=result.order;
 let title=s.outcome==='success'?'预约已创建':'预约未完成';let html=`<div class="result-stage ${s.outcome==='success'?'':'error'}"><strong>${e(s.message||'请核实预约结果')}</strong></div>`;
 if(s.preview)html+=`<p>${e(s.preview.location)}<br>${e(s.preview.start)} — ${e(s.preview.end)}</p>`;
 if(o){$('#price').textContent='¥ '+o.configuration.expectedAmount;$('#price-unit').textContent='元';html+=`<p>订单金额：¥ ${e(o.configuration.expectedAmount)}<br>支付期限：${e(o.expiresAt)}</p>`;}
 if(p){const names={insufficient_balance:'余额不足，未付款',expired_or_cancelled:'订单已过期或取消',rejected:'支付未成功',accepted:'支付已受理，待核实最终状态',unknown:'支付结果未知，请勿重复支付'};title=names[p.outcome]||title;html+=`<div class="result-stage ${p.outcome==='accepted'?'':'error'}">${e(p.message||names[p.outcome]||p.outcome)}</div>`;}
 if(result.errors)html+=`<p>${e(result.errors.map(x=>x.message).join('；'))}</p>`;
 html+='<p>预约及支付记录已保存在本机。请在「订单记录」中查询原订单，避免重新预约。</p>';
 S.live=null;S.received=0;renderMap();renderSlots();updateButtons();message(title,s.message||p?.message||'在订单记录中核对结果。');showResult(title,html);
}
async function submitBooking(){
 if(S.busy||!fresh()||!selectedSlot()?.available)return;
 const config=cfg(),pay=$('#pay-toggle').checked;
 ask(pay?'确认预约并支付':'确认本次预约',`<p><strong>${e(S.court.name)}</strong></p><p>${e(dateLabel(S.date))}<br><strong>${e(S.start)} — ${e(S.end)}</strong></p><p>支付方式：${pay?'校园卡，按订单实际金额':'暂不支付'}</p>`,pay?'确认后会创建预约，并按新订单金额发起一次真实校园卡支付。余额充足时可能扣款。':'确认后会创建预约并自动获取订单，不发起支付。订单可能有较短支付期限。',()=>task('正在创建预约，请勿重复提交…',async()=>{
  const result=await api('book',{config,pay,confirmed:true,requestId:crypto.randomUUID()});bookingResult(result);
 }));
}
async function showView(view){
 if(S.busy)return;S.view=view;document.querySelectorAll('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
 $('#explore-view').hidden=view!=='explore';$('#booking-panel').hidden=view!=='explore';$('#automation-view').hidden=view!=='automation';$('#secondary-view').hidden=view==='explore'||view==='automation';
 if(view==='automation'){window.AutomationUI.open();return;}
 if(view==='explore'){if(!fresh())await task('刷新场地状态…',refreshLive);return;}
 const titles={records:'我的预约',orders:'订单记录',settings:'登录设置'};$('#secondary-title').textContent=titles[view];$('#secondary-content').innerHTML='<div class="empty">正在打开训练家手册…</div>';
 await task('正在读取'+titles[view]+'…',()=>loadSecondary());
}
async function loadSecondary(){
 if(S.view==='records'){
  const d=await api('records',{date:S.date});
  $('#secondary-content').innerHTML=`<p class="records-intro">${e(dateLabel(S.date))} · 共 ${d.total} 条预约记录 · 来自学校网站</p><br><div class="record-list">${d.rows.map(r=>`<article class="record-card"><div><h3>${e(r.infoName)}</h3><p>${e(r.recordTimeStart)} — ${e(r.recordTimeEnd)}</p><p>预约编号 ${e(r.occupyId)}</p></div><div><span class="badge">${e(r.recordUseStatus)}</span><p>${r.feePayStatus==='0'?'未支付':'支付状态：'+e(r.feePayStatus)}</p></div></article>`).join('')||'<div class="empty">这一天还没有预约记录。去道馆看看吧！</div>'}</div>`;
 }else if(S.view==='orders'){
  const d=await api('orders');$('#secondary-content').innerHTML=`<p>本机保存的订单。点击「查状态」从网站核对，过期订单不能继续付款。</p><br><div class="record-list">${d.orders.map(o=>{const c=S.courts.find(c=>c.infoId===o.infoId);return `<article class="record-card"><div><h3>${e(c?.name||'羽毛球预约')} · ¥ ${e(o.expectedAmount)}</h3><p>${e(o.start)} — ${e(o.end)}</p><p>订单 ${e(o.feeOrderId)}</p><p class="order-state" data-state-key="${e(o.key)}">尚未查询当前状态</p></div><div class="record-actions"><button class="button compact" data-order-status="${e(o.key)}">查状态</button><button class="button compact" data-order-pay="${e(o.key)}" data-amount="${e(o.expectedAmount)}">支付原订单</button></div></article>`;}).join('')||'<div class="empty">还没有保存的订单。预约创建后会自动出现在这里。</div>'}</div>`;
 }else if(S.view==='settings'){
  $('#secondary-content').innerHTML=window.LoginUI.render();
  await window.LoginUI.open();
 }
}
async function boot(){
 art();try{const r=await fetch('/api/bootstrap');if(!r.ok)throw Error('本地服务无法连接');const d=await r.json();S.courts=d.courts;S.today=d.today;S.date=d.config.date<S.today?S.today:d.config.date;S.court=S.courts.find(c=>c.infoId===d.config.venue||c.name===d.config.venue)||S.courts[0];S.group=S.court.group;S.start=d.config.start;S.end=d.config.end;renderSelection();document.querySelectorAll('[data-group]').forEach(b=>{b.classList.toggle('active',b.dataset.group===S.group);b.setAttribute('aria-selected',b.dataset.group===S.group);});
  window.dispatchEvent(new Event('catalog-ready'));
  if(!d.sessionStored){message('欢迎来到道馆','先登录自己的学校账号，并填写预约联系电话。');await showView('settings');return;}
  await task('正在核对训练家通行证…',async()=>{try{await sessionCheck();}catch(err){$('#session-pill').textContent='● 连接待检查';$('#session-pill').style.color='var(--red)';$('#slots').innerHTML='<div class="empty">登录或连接未通过检查<br>请到「登录设置」核实</div>';$('#slot-source').textContent='状态未知';throw err;}const freshCatalog=await api('catalog');S.courts=freshCatalog.courts;S.court=S.courts.find(c=>c.infoId===S.court.infoId)||S.courts[0];S.group=S.court.group;await refreshLive();});
 }catch(err){message('道馆暂时未连接',err.message);toast(err.message);}
 if(location.hash==='#automation'&&S.courts.length)showView('automation');
}
document.addEventListener('click',async ev=>{
 const b=ev.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.view)return showView(b.dataset.view);
 if(b.dataset.group)return switchGroup(b.dataset.group);
 if(b.dataset.date)return switchDate(b.dataset.date);
 if(b.dataset.court){if(S.busy)return;S.court=S.courts.find(c=>c.infoId===b.dataset.court);resetPrice();renderSelection();return;}
 if(b.dataset.start){if(S.busy)return;resetPrice();S.start=b.dataset.start;S.end=b.dataset.end;renderSelection();return;}
 if(b.dataset.orderStatus)return task('正在核对订单状态…',async()=>{const d=await api('order-status',{key:b.dataset.orderStatus});const label=d.feePayStatus==='1'?'已支付':d.feePayStatus==='0'?'未支付':'支付状态 '+d.feePayStatus;const state=$(`[data-state-key="${b.dataset.orderStatus}"]`);state.textContent=`${label} · 订单状态 ${d.feeOrderStatus} · 截止 ${d.feeOrderExpiredDate||'未提供'}`;if(d.feeOrderStatus!=='0'||d.feePayStatus!=='0')b.closest('.record-card').querySelector('[data-order-pay]').disabled=true;});
 if(b.dataset.orderPay){const key=b.dataset.orderPay;return ask('支付这笔原订单？',`<p>金额：<strong>¥ ${e(b.dataset.amount)}</strong></p><p>将再次向网站核对订单、账号和金额。</p>`,'这会发送一次真实校园卡支付请求。订单已过期、已支付或结果未知时，程序会停止重复支付。',()=>task('正在支付原订单…',async()=>{const d=await api('pay',{key,confirmed:true,requestId:crypto.randomUUID()});showResult('支付结果',`<p>${e(d.payment.message||d.payment.outcome)}</p><p>支付受理不等于最终扣款成功，请再次查询订单状态。</p>`);}));}
 switch(b.id){
  case 'refresh':return task('正在刷新学校实时数据…',refreshLive);
  case 'book':return submitBooking();
  case 'check':return task('正在检查所选时段…',async()=>{await api('check',{config:cfg()});message('场地和配置检查通过','实际预约仍由服务器核对占用、账号次数及其他条件。');toast('检查通过；未创建预约，也未支付。');});
  case 'save-config':if(!S.start)return toast('请先选择完整时段');return task('保存选择…',async()=>{await api('save',{config:cfg()});toast('已保存当前场地、日期和时段。');});
  case 'session-pill':case 'verify-login':return task('检查登录…',async()=>{await sessionCheck();toast('学校登录会话有效。');});
  case 'renew-login':return task('正在尝试学校认证续期…',async()=>{await sessionCheck(true);toast('续期验证通过。');});
  case 'reload-secondary':return task('正在刷新…',loadSecondary);
  case 'refresh-catalog':return task('正在更新场地目录…',async()=>{const d=await api('catalog');S.courts=d.courts;S.live=null;toast(`已从网站更新 ${d.courts.length} 块羽毛球场。`);});
  case 'import-login':return task('正在导入并验证会话…',async()=>{const file=$('#session-file').files[0];if(!file)throw Error('请先选择凭据 JSON 文件');if(file.size>90000)throw Error('凭据文件过大');const credentials=JSON.parse(await file.text());await api('import',{credentials});await sessionCheck();$('#session-file').value='';toast('会话已验证并加密保存在本机。');});
 }
});
$('#court-select').addEventListener('change',()=>{resetPrice();S.court=S.courts.find(c=>c.infoId===$('#court-select').value);renderSelection();});
$('#date-input').addEventListener('change',()=>switchDate($('#date-input').value));
$('#confirm-dialog').addEventListener('close',()=>{const run=S.confirming;S.confirming=null;if($('#confirm-dialog').returnValue==='submit'&&run)run();});
setInterval(()=>{if(!document.hidden&&S.view==='explore'&&!S.busy&&!$('dialog[open]'))task('正在自动更新场地状态…',refreshLive);},60000);
setInterval(()=>{if(S.live&&!fresh()){renderMap();renderSlots();updateButtons();$('#sync-time').textContent='状态已过期，请刷新';}},10000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.view==='explore'&&!S.busy&&!fresh()&&!$('dialog[open]'))task('恢复实时查询…',refreshLive);});
window.addEventListener('DOMContentLoaded',boot,{once:true});
