const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');

test('fetch synchronizer token stays on this origin and covers POST FormData', async () => {
  const calls=[];
  const window={fetch: async (...args)=>{calls.push(args);return {ok:true};}};
  const ctx={window,URL,Headers,Request,location:{href:'https://farm.test/dashboard',origin:'https://farm.test'},
    document:{querySelector:()=>({content:'secret-csrf'})}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'static/js/security.js'),'utf8'),ctx);
  await window.fetch('/api/push/test',{method:'POST'});
  assert.equal(calls[0][1].headers.get('X-CSRF-Token'),'secret-csrf');
  await window.fetch('https://outside.test/api',{method:'POST'});
  assert.equal(calls[1][1].headers,undefined);
  await window.fetch('/api/farms');assert.equal(calls[2][1].headers,undefined);
  await window.fetch(new Request('https://farm.test/api/test',{method:'POST'}));
  assert.equal(calls[3][1].headers.get('X-CSRF-Token'),'secret-csrf');
});

function worker() {
  const handlers={}, removed=[], put=[], fallback={publicShell:true}, stores=['gf-pages-v4','gf-static-v4','gf-static-v5-security'];
  const ctx={URL,Response,BroadcastChannel:undefined,setTimeout,clearTimeout,
    fetch:async()=>{throw Error('offline')},
    caches:{keys:async()=>stores,delete:async key=>removed.push(key),match:async()=>fallback,
      open:async()=>({put:async(...args)=>put.push(args),match:async()=>null,add:async()=>{}})},
    self:{location:{origin:'https://farm.test'},addEventListener:(name,fn)=>handlers[name]=fn,
      skipWaiting(){},clients:{claim:async()=>{}},registration:{}}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'static/sw.js'),'utf8'),ctx);
  return {handlers,removed,put,fallback,ctx};
}

test('upgrade erases legacy private cache', async()=>{
  const w=worker();let promise;
  w.handlers.activate({waitUntil:p=>promise=p});await promise;
  assert.ok(w.removed.includes('gf-pages-v4'));assert.ok(w.removed.includes('gf-static-v4'));
  assert.ok(!w.removed.includes('gf-static-v5-security'));
});

test('offline navigation never reads a private cache and online never stores HTML', async()=>{
  const w=worker();let result;
  const event={request:{method:'GET',mode:'navigate',url:'https://farm.test/profile'},respondWith:p=>result=p};
  w.handlers.fetch(event);assert.equal(await result,w.fallback);assert.equal(w.put.length,0);
  w.ctx.fetch=async()=>({privateResponse:true});w.handlers.fetch(event);
  assert.deepEqual(await result,{privateResponse:true});assert.equal(w.put.length,0);
});

test('notification click refuses navigation off site',async()=>{
  const w=worker();let promise,destination;
  w.ctx.self.clients.matchAll=async()=>[];w.ctx.self.clients.openWindow=async url=>destination=url;
  w.handlers.notificationclick({notification:{close(){},data:{url:'https://outside.test/phish'}},waitUntil:p=>promise=p});
  await promise;assert.equal(destination,'/dashboard');
});
