import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {setTimeout as delay} from 'node:timers/promises';
import {CDP} from './cdp.mjs';
import {collectCredentials, PAGE_SESSION} from './credentials.mjs';

const APP='https://resm.lzjtu.edu.cn';
let browser,profile,connection,cancelled=false;
process.on('SIGINT',()=>{cancelled=true;});
process.on('SIGTERM',()=>{cancelled=true;});
async function findBrowser(){
  const candidates=[];
  if(process.platform==='win32'){
    for(const root of [process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)'],process.env.LOCALAPPDATA].filter(Boolean)){
      candidates.push(path.join(root,'Google/Chrome/Application/chrome.exe'),path.join(root,'Microsoft/Edge/Application/msedge.exe'));
    }
  }else if(process.platform==='darwin'){
    for(const root of ['/Applications',path.join(os.homedir(),'Applications')]){
      candidates.push(path.join(root,'Google Chrome.app/Contents/MacOS/Google Chrome'),path.join(root,'Microsoft Edge.app/Contents/MacOS/Microsoft Edge'));
    }
  }else throw Error('此启动包支持 Windows 和 macOS。');
  for(const candidate of candidates){try{await fs.access(candidate);return candidate;}catch{}}
  throw Error('未找到 Chrome 或 Edge，请先安装其中一个浏览器，再运行此脚本。');
}
async function clipboard(text){
  const command=process.platform==='darwin'?'/usr/bin/pbcopy':'powershell.exe';
  const args=process.platform==='darwin'?[]:['-NoProfile','-NonInteractive','-Command','[Console]::InputEncoding=[System.Text.UTF8Encoding]::new(); $questText=[Console]::In.ReadToEnd(); Set-Clipboard -Value $questText'];
  await new Promise((resolve,reject)=>{
    const child=spawn(command,args,{windowsHide:true,stdio:['pipe','ignore','ignore']});
    const timer=setTimeout(()=>{child.kill();reject(Error('复制超时'));},8000);
    child.on('error',()=>{clearTimeout(timer);reject(Error('无法访问剪贴板'));});
    child.on('exit',code=>{clearTimeout(timer);code===0?resolve():reject(Error('复制失败'));});
    child.stdin.on('error',()=>{});child.stdin.end(text,'utf8');
  });
}
async function cleanup(){
  if(connection){try{await connection.send('Browser.close');}catch{}connection.close();}
  if(browser&&browser.exitCode===null){
    await Promise.race([new Promise(resolve=>browser.once('exit',resolve)),delay(3000)]);
    if(browser.exitCode===null){browser.kill();await delay(1000);}
  }
  // Delete only the exact disposable profile created by this run, never a daily browser profile.
  if(profile&&path.dirname(path.resolve(profile))===path.resolve(os.tmpdir())&&path.basename(profile).startsWith('quest-school-login-')){
    try{await fs.rm(profile,{recursive:true,force:true,maxRetries:8,retryDelay:250});}
    catch{console.log('临时登录目录未能完全清理，请关闭此次登录窗口后删除：'+profile);}
  }
}
async function main(){
  const executable=await findBrowser();
  console.log('羽球训练家 · 本地会话提取\n将在独立窗口打开学校网站，请完成登录并进入预约首页。');
  console.log('脚本只读取这次独立登录的学校会话（含 HttpOnly Cookie），成功后复制到剪贴板。');
  console.log(process.argv.includes('--no-sso')?'本次不包含统一认证 Cookie。':'同时包含本次登录的统一认证 Cookie，供服务器尝试续期。');
  console.log('不会自动上传、预约或付款。可按 Ctrl+C 取消，最长等待 10 分钟。');
  profile=await fs.mkdtemp(path.join(os.tmpdir(),'quest-school-login-'));
  browser=spawn(executable,['--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--window-size=1120,800','about:blank'],{stdio:'ignore'});
  let launchError=false;browser.once('error',()=>{launchError=true;});
  let portData;
  for(let i=0;i<80;i++){
    if(cancelled)throw Error('已取消。');
    if(launchError||browser.exitCode!==null)throw Error('独立登录浏览器启动失败或已关闭。');
    try{portData=(await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).trim().split(/\r?\n/);if(portData.length>=2)break;}catch{}
    await delay(250);
  }
  if(!portData||!/^\d+$/.test(portData[0])||!portData[1]?.startsWith('/devtools/browser/'))throw Error('登录浏览器初始化超时，请重试。');
  connection=await CDP.connect('ws://127.0.0.1:'+portData[0]+portData[1]);
  const sessions=new Map(),tokens=new Map();
  connection.listeners.add(event=>{
    if(event.method!=='Network.requestWillBeSent')return;
    const request=event.params?.request;
    if(!request?.url.startsWith(APP+'/'))return;
    const token=Object.entries(request.headers||{}).find(([key])=>key.toLowerCase()==='x-access-token')?.[1];
    if(token){const values=tokens.get(event.sessionId)||[];values.unshift(token);tokens.set(event.sessionId,[...new Set(values)].slice(0,8));}
  });
  const initial=(await connection.send('Target.getTargets')).targetInfos.find(t=>t.type==='page');
  if(initial){
    const {sessionId}=await connection.send('Target.attachToTarget',{targetId:initial.targetId,flatten:true});
    sessions.set(initial.targetId,sessionId);await connection.send('Network.enable',{},sessionId);
    await connection.send('Page.navigate',{url:APP+'/'},sessionId);
  }else await connection.send('Target.createTarget',{url:APP+'/'});
  const deadline=Date.now()+600000;
  while(Date.now()<deadline){
    if(cancelled)throw Error('已取消。');
    if(browser.exitCode!==null||connection.socket.readyState!==WebSocket.OPEN)throw Error('登录窗口已关闭，未导出会话。');
    const targets=(await connection.send('Target.getTargets')).targetInfos.filter(t=>t.type==='page'&&t.url.startsWith(APP+'/'));
    for(const target of targets){
      try{
        let sessionId=sessions.get(target.targetId);
        if(!sessionId){({sessionId}=await connection.send('Target.attachToTarget',{targetId:target.targetId,flatten:true}));sessions.set(target.targetId,sessionId);await connection.send('Network.enable',{},sessionId);}
        const result=await connection.send('Runtime.evaluate',{expression:PAGE_SESSION,returnByValue:true},sessionId);
        const {cookies}=await connection.send('Storage.getCookies');
        const credentials=collectCredentials(result.result?.value,cookies,tokens.get(sessionId),{includeSso:!process.argv.includes('--no-sso')});
        if(!credentials)continue;
        const text=JSON.stringify(credentials,null,2);
        try{await clipboard(text);console.log('\n已提取并复制完整会话！回到羽球训练家 → 登录设置 → 粘贴 JSON → 验证并保存。');}
        catch{console.log('\n自动复制失败，请手动复制下面从 { 到 } 的完整 JSON：\n'+text);}
        console.log('提取成功不代表云端验证已通过；请以网站的验证结果为准。请勿公开分享这些凭据。');
        return;
      }catch(error){if(cancelled)throw error;/* The school may navigate while its login state is read. */}
    }
    await delay(1000);
  }
  throw Error('等待登录超时。若学校页面空白，请稍后重新运行；完成登录后必须进入预约首页。');
}
try{await main();}catch(error){console.error('\n'+error.message);process.exitCode=1;}finally{await cleanup();}
