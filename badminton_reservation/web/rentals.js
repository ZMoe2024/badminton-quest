'use strict';
// Web-only view: all data comes from the server's privacy-filtered rental API.
window.RentalUI=(()=>{
 let model={offers:[],mine:[],orders:[],courts:[]},tab='market',selection=null,slotList=[],slotTime=0;
 const name=id=>model.courts.find(c=>c.id===id)?.name||'羽毛球场';
 const when=t=>new Date(t*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
 async function request(action,body){
  const response=await fetch('/api/rentals'+(action?'/'+action:''),action?{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(body)}:{});
  const result=await response.json();if(!response.ok||result.error)throw Error(result.error||'租约服务暂未回应');return result;
 }
 async function open(){model=await request();render();}
 function offerCard(o,own=false){return `<article class="rental-card"><div class="rental-card-head"><span class="rental-seal" aria-hidden="true">◇</span><div><h3>${e(o.label)}</h3><p>${own?(o.available?'授权已开放':'授权已关闭'):o.courts.length+' 块可选场地'} · 按次预约</p></div><strong>¥ ${e(o.fee)}<small>服务费 / 次</small></strong></div><p class="rental-court-names">${e(o.courts.map(name).join(' · '))}</p><p class="rental-muted">新单授权截至 ${e(when(o.expires))}</p>${own?`<p>剩余授权 <b>${o.remaining}</b> 次 · 每单场地费上限 <b>¥ ${e(o.maxAmount)}</b></p><button class="button compact" data-rental-revoke="${e(o.id)}" ${!o.available?'disabled':''}>下架授权</button>`:`<button class="button primary" data-rental-select="${e(o.id)}">选择场地与时段 →</button>`}</article>`;}
 function render(){
  const root=$('#secondary-content');if(S.view!=='rentals')return;
  root.innerHTML=`<div class="rentals"><header class="rental-intro"><div><span class="rental-kicker">TRAINER EXCHANGE</span><h2>借一份授权，赴一场球约。</h2><p>按次接单 · 隐藏账号资料 · 校园卡限额扣款</p></div><span class="rental-pixel" aria-hidden="true">↔</span></header><div class="rental-notice">服务费由出借人填写，平台仅展示与记录，<b>不代收、不标记为已付款</b>。学校场地费另由出借人的校园卡按授权扣除。入场仍以学校核验为准。</div><nav class="rental-tabs" aria-label="租约分类">${[['market','找一个场地授权'],['mine','我的出借授权'],['orders','租约记录']].map(([key,text])=>`<button class="${tab===key?'active':''}" data-rental-tab="${key}" aria-pressed="${tab===key}">${text}</button>`).join('')}</nav><div id="rental-body">${tab==='market'?market():tab==='mine'?mine():orders()}</div></div>`;
 }
 function market(){
  if(selection){
   const offer=model.offers.find(o=>o.id===selection);
   if(!offer){selection=null;return market();}
   const tomorrow=dayOffset(S.today||new Date().toISOString().slice(0,10),1);
   return `<button class="button compact" id="rental-back">← 所有授权</button><section class="rental-form"><h3>${e(offer.label)} · 服务费 ¥ ${e(offer.fee)} / 次</h3><p class="rental-muted">只向后台提交预约需求，不获取或接管对方账号。</p><div class="rental-fields"><label>选择场地<select id="rental-court">${offer.courts.map(id=>`<option value="${e(id)}">${e(name(id))}</option>`).join('')}</select></label><label>预约日期<input type="date" id="rental-date" min="${e(S.today)}" value="${e(tomorrow)}"></label><button class="button" id="rental-query">查询学校实时可用时段</button></div><div id="rental-slots" class="rental-slots"><p class="rental-muted">先查询学校时段，再选择可预约的时段。未查询的场地不会显示为空闲。</p></div><p class="rental-muted">接单后会提交一次真实预约，并在出借人的上限内支付学校场地费。服务费由双方另行约定结算，平台不提供收款或匿名聊天。</p></section>`;
  }
  return `<div class="rental-grid">${model.offers.map(o=>offerCard(o)).join('')||'<div class="empty">暂时没有开放的场地授权。<br>已有学校账号的训练家可以在「我的出借授权」发布。</div>'}</div>`;
 }
 function mine(){return `<div class="rental-own-layout"><form id="rental-publish" class="rental-form"><h3>发布一份限次授权</h3><p class="rental-muted">需要先验证自己的学校会话并填写联系电话。发布后，在授权范围内的新单会自动提交和扣款，无需逐单确认。</p><div class="rental-fields"><label>服务费 / 次（仅展示）<input name="fee" type="number" min="0" max="10000" step="0.01" value="5.00" required></label><label>每单场地费扣款上限<input name="maxAmount" type="number" min="0.01" max="10000" step="0.01" value="50.00" required></label><label>最多接受几次申请<input name="uses" type="number" min="1" max="20" value="1" required></label><label>新单授权有效期（小时）<input name="hours" type="number" min="1" max="168" value="24" required></label></div><fieldset class="rental-courts"><legend>允许预约的羽毛球场地</legend>${model.courts.map(c=>`<label><input type="checkbox" name="courts" value="${e(c.id)}">${e(c.name)}</label>`).join('')}</fieldset><p class="rental-muted">每份申请一经接单即占用一次授权，包括未约成或结果待核实的申请；不会自动补回次数。有效期限制新单受理时间，预约日期可在未来 30 天内。服务费不从校园卡扣除。</p><label class="rental-consent"><input name="authorized" type="checkbox" required><span>我确认有权授权此学校账号，在上述次数、场地和每单金额上限内接受他人的预约需求，并从<b>我的校园卡</b>直接支付学校场地费。我理解平台不代收服务费。</span></label><button class="button primary" type="submit">核对并发布授权</button></form><div><h3>已发布的授权</h3><p class="rental-muted">下架只停止接新单，已接单仍按原授权处理。</p><div class="rental-grid rental-single">${model.mine.map(o=>offerCard(o,true)).join('')||'<div class="empty">还没有发布授权。</div>'}</div></div></div>`;}
 function orders(){return `<p class="rental-muted">仅显示本人的出借与租用记录。服务费未由平台收取；“学校已支付”只代表学校场地费。</p><div class="rental-grid rental-single">${model.orders.map(o=>`<article class="rental-card rental-order"><div><p class="rental-kicker">${o.role==='owner'?'我出借的':'我租用的'} · ${e(o.label)}</p><h3>${e(name(o.config.venue))} · ${e(o.config.date)}</h3><p>${e(o.config.start)} — ${e(o.config.end)}<br>服务费 ¥ ${e(o.fee)}（平台未收取） · 学校场地费 ${o.amount?'¥ '+e(o.amount):'查单后显示'}</p><p class="rental-status ${o.state==='paid'?'paid':''}">${e(o.message)}</p><small>本站租约 ${e(o.id)} · ${e(when(o.created))}</small></div><div class="rental-order-actions">${o.state==='queued'?`<button class="button" data-rental-run="${e(o.id)}">处理已接订单</button>`:''}${o.canCheck?`<button class="button" data-rental-check="${e(o.id)}">向学校核实支付</button>`:''}${o.role==='owner'?'<small>其他异常请到「我的预约」「订单记录」核对原单。</small>':''}</div></article>`).join('')||'<div class="empty">还没有租约记录。</div>'}</div>`;}
 document.addEventListener('click',ev=>{
  const b=ev.target.closest('button');if(!b||b.disabled||S.busy)return;
  if(b.dataset.rentalTab){tab=b.dataset.rentalTab;selection=null;$('#secondary-content').scrollTop=0;return task('刷新租约…',open);}
  if(b.dataset.rentalSelect){selection=b.dataset.rentalSelect;slotList=[];return render();}
  if(b.id==='rental-back'){selection=null;return render();}
  if(b.dataset.rentalRevoke){const id=b.dataset.rentalRevoke;return ask('停止接受新租约？','<p>这份授权将立即下架。</p>','已接单仍按原授权处理；不会取消学校预约或退款。',()=>task('下架授权…',async()=>{await request('revoke',{offerId:id});await open();}));}
  if(b.id==='rental-query')return task('正在向学校查询这块场地…',async()=>{
   slotList=[];$('#rental-slots').textContent='正在核实时段…';
   try{const config={offerId:selection,venue:$('#rental-court').value,date:$('#rental-date').value};const data=await request('slots',config);slotTime=Date.now();slotList=data.slots.map(s=>({...s,venue:config.venue,date:config.date}));$('#rental-slots').innerHTML=slotList.map((s,i)=>`<button class="rental-slot ${s.available?'available':''}" data-rental-slot="${i}" ${s.available?'':'disabled'}><strong>${e(s.start)} — ${e(s.end)}</strong><small>${s.available?'可申请预约':'不可预约'}</small></button>`).join('')||'<p>学校未返回当天时段。</p>';}
   catch(err){$('#rental-slots').textContent='实时查询未完成，请刷新；未使用旧的空闲状态。';throw err;}
  });
  if(b.dataset.rentalSlot!==undefined){
   const slot=slotList[Number(b.dataset.rentalSlot)],offer=model.offers.find(o=>o.id===selection);
   if(!slot||!offer||!slot.available)return;
   if(Date.now()-slotTime>90000)return toast('时段状态已过期，请重新查询学校实时状态。');
   const body={offerId:offer.id,fee:offer.fee,config:{venue:slot.venue,date:slot.date,start:slot.start,end:slot.end},confirmed:true,requestId:crypto.randomUUID()};
   return ask('确认按次租约并预约？',`<p><b>${e(name(slot.venue))}</b><br>${e(slot.date)} ${e(slot.start)} — ${e(slot.end)}</p><p>${e(offer.label)}<br>服务费：<b>¥ ${e(offer.fee)}</b>（平台未收取）</p>`,'确认后会实际创建预约，并按出借人的授权尝试扣除学校场地费。学校入场要求需自行核实。',()=>task('正在接单并预约，请勿重复操作…',async()=>{
    try{const data=await request('request',body);toast(data.notice||data.order.message);}
    finally{tab='orders';selection=null;await open();}
   }));
  }
  const id=b.dataset.rentalRun||b.dataset.rentalCheck;
  if(id)return task('核实原租约…',async()=>{const data=await request(b.dataset.rentalRun?'run':'check',{id});toast(data.notice||data.order.message);await open();});
 });
 document.addEventListener('change',ev=>{if(['rental-court','rental-date'].includes(ev.target.id)){slotList=[];$('#rental-slots').innerHTML='<p>选择已改变，请重新查询学校实时状态。</p>';}});
 document.addEventListener('submit',ev=>{
  if(ev.target.id!=='rental-publish')return;ev.preventDefault();if(S.busy)return;
  const form=new FormData(ev.target),body={fee:form.get('fee'),maxAmount:form.get('maxAmount'),uses:Number(form.get('uses')),hours:Number(form.get('hours')),courts:form.getAll('courts'),authorized:form.has('authorized')};
  if(!body.courts.length)return toast('至少选择一块允许预约的场地。');
  const total=(Number(body.maxAmount)*body.uses).toFixed(2);
  ask('授权校园卡自动扣款？',`<p>最多 <b>${body.uses}</b> 次申请，每单学校场地费不超过 <b>¥ ${e(body.maxAmount)}</b>。<br>本份授权累计最多扣除 <b>¥ ${e(total)}</b> 学校场地费。</p><p>允许 ${body.courts.length} 块场地，新单有效期 ${body.hours} 小时。<br>服务费 ¥ ${e(body.fee)} / 次，平台不收取。</p>`,'授权发布后无需逐单确认。仅对本站其他用户隐藏身份，学校仍使用你的真实账号预约。',()=>task('验证学校会话并发布授权…',async()=>{await request('publish',body);await open();toast('限次授权已发布，可随时下架停止接新单。');}));
 });
 window.addEventListener('DOMContentLoaded',()=>{
  const nav=$('.sidebar nav');if(!nav)return;
  const button=document.createElement('button');button.className='nav-item';button.dataset.view='rentals';button.innerHTML='<span aria-hidden="true">◇</span> 匿名租约';nav.append(button);
 });
 return {open};
})();
