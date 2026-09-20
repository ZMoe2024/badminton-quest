import test from 'node:test';
import assert from 'node:assert/strict';
import {collectCredentials} from './credentials.mjs';
const encode = x => Buffer.from(JSON.stringify(x)).toString('base64url');
function fixture(){
  return {
    page:{origin:'https://resm.lzjtu.edu.cn',currentUser:encode({username:'demo',userId:'fixture'}),token:'h.'+encode({username:'demo',exp:9999999999})+'.s',userAgent:'Fixture'},
    cookies:[
      {name:'evbSrBv8QGpBO',value:'fixture-http-only',domain:'resm.lzjtu.edu.cn',path:'/',httpOnly:true},
      {name:'evbSrBv8QGpBP',value:'fixture-js',domain:'resm.lzjtu.edu.cn',path:'/'},
      {name:'CASTGC',value:'fixture-sso',domain:'authserver.lzjtu.edu.cn',path:'/authserver'},
      {name:'other',value:'never-export',domain:'unrelated.test',path:'/'}
    ]
  };
}
test('exports HttpOnly app cookies and only school authentication cookies',()=>{
  const {page,cookies}=fixture();const result=collectCredentials(page,cookies);
  assert.equal(result.cookies.length,2);assert.equal(result.cookies[0].value,'fixture-http-only');
  assert.deepEqual(result.ssoCookies.map(c=>c.name),['CASTGC']);
  assert.ok(!JSON.stringify(result).includes('never-export'));
});
test('no-sso option omits the authentication session',()=>{
  const {page,cookies}=fixture();assert.equal(collectCredentials(page,cookies,[],{includeSso:false}).ssoCookies,undefined);
});
test('wrong origin, incomplete cookies, expired token and mismatched identity return no result',()=>{
  const {page,cookies}=fixture();
  assert.equal(collectCredentials({...page,origin:'https://evil.test'},cookies),null);
  assert.equal(collectCredentials(page,cookies.slice(1)),null);
  for(const claims of [{username:'other',exp:9999999999},{username:'demo',exp:1}])
    assert.equal(collectCredentials({...page,token:'h.'+encode(claims)+'.s'},cookies),null);
});
test('uses a captured matching request token if storage token is stale',()=>{
  const {page,cookies}=fixture();const valid=page.token;
  assert.equal(collectCredentials({...page,token:'invalid'},cookies,[valid]).token,valid);
});
