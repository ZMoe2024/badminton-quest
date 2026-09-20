'use strict';
let mode='login';
const form=document.querySelector('#auth-form'),error=document.querySelector('#auth-error'),submit=document.querySelector('#auth-submit');
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{
 mode=button.dataset.mode;document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-selected',b===button));
 document.querySelector('#invite-row').hidden=mode!=='register';document.querySelector('#invite').required=mode==='register';
 document.querySelector('#password').autocomplete=mode==='register'?'new-password':'current-password';
 document.querySelector('#auth-title').textContent=mode==='register'?'领取你的训练家通行证':'欢迎回到道馆';
 submit.textContent=mode==='register'?'创建账号并进入道馆':'进入道馆 ›';error.textContent='';
}));
form.addEventListener('submit',async event=>{
 event.preventDefault();submit.disabled=true;error.textContent='';
 try{
  const body=Object.fromEntries(new FormData(form));
  const response=await fetch('/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'登录失败');location.assign('/');
 }catch(exc){error.textContent=exc.message;}finally{submit.disabled=false;}
});
