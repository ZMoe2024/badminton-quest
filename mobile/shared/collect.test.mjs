import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const script=fs.readFileSync(new URL('./collect.js',import.meta.url),'utf8');
const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
function run({origin='https://resm.lzjtu.edu.cn',username='fixture',exp=Date.now()/1000+600,currentUser,token}={}){
 const values={currentUser:currentUser??b64({username:'fixture',userId:'id',name:'测试'}),token:token??`x.${b64({username,exp})}.x`};
 return vm.runInNewContext(script,{location:{origin},document:{cookie:''},localStorage:{getItem:k=>values[k]},sessionStorage:{getItem:()=>null},navigator:{userAgent:'fixture'},TextDecoder,Uint8Array,atob,Date});
}
test('exports matching school identity and handles Unicode Base64URL',()=>{
 const data=run();assert.equal(data.ok,true);assert.equal(data.currentUser.name,'测试');assert.equal(data.userAgent,'fixture');
});
test('never exports from other origins, expired or mismatched identities',()=>{
 for(const options of [{origin:'https://evil.example'},{origin:'http://resm.lzjtu.edu.cn'},{username:'someone-else'},{exp:0},{currentUser:'broken'},{token:'broken'}]){
  const data=run(options);assert.equal(data.ok,false);assert.equal(data.token,undefined);
 }
});
