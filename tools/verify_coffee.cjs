const {chromium}=require(process.env.PW_PATH),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
(async()=>{
 const base='http://127.0.0.1:'+process.argv[2],remote='http://nas.preview.test:'+process.argv[2];
 const b=await chromium.launch({executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',headless:true,args:['--no-proxy-server','--host-resolver-rules=MAP nas.preview.test 127.0.0.1']});
 try{
  const ctx=await b.newContext({viewport:{width:1366,height:900}});
  assert.equal((await ctx.request.get(base+'/product-icon.png')).status(),200);
  const password=require('crypto').randomBytes(20).toString('hex');
  assert((await (await ctx.request.post(base+'/api/auth/setup',{headers:{'X-FNM-Request':'1'},data:{password}})).json()).ok);
  // Assets stay behind authentication; URLs cannot traverse into the app/data tree.
  const anon=await b.newContext();assert.equal((await anon.request.get(base+'/coffee/alipay.png')).status(),401);await anon.close();
  for(const name of ['alipay.png','wechat.png']){
   const r=await ctx.request.get(base+'/coffee/'+name);assert.equal(r.status(),200);assert.deepEqual(await r.body(),fs.readFileSync(path.resolve(__dirname,'../app/www/coffee',name)));
   assert((await ctx.request.post(base+'/coffee/'+name,{headers:{'X-FNM-Request':'1'},data:{image:'replace'}})).status()>=400);
  }
  assert.equal((await ctx.request.get(base+'/coffee/not-an-asset')).status(),404);
  const p=await ctx.newPage(),errors=[],images=[];p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(/coffee\/(alipay|wechat)/.test(r.url()))images.push(r.url());});
  await p.goto(base+'/launcher.html');await p.locator('#fn-coffee').waitFor();assert.equal(images.length,0);assert.equal(await p.locator('#fn-coffee-dialog').isVisible(),false);
  await p.locator('#fn-coffee').click();await p.locator('#fn-coffee-dialog img').evaluateAll(es=>Promise.all(es.map(e=>e.decode())));
  assert.equal(images.length,2);assert.deepEqual(await p.locator('figcaption').allTextContents(),['支付宝','微信']);
  assert.equal(await p.locator('#fn-coffee-dialog input').count(),0);
  const out=path.resolve(__dirname,'../validation');fs.mkdirSync(out,{recursive:true});await p.screenshot({path:out+'/coffee-desktop.png'});
  await p.keyboard.press('Escape');assert.equal(await p.locator('#fn-coffee-dialog').isVisible(),false);assert.equal(await p.locator('#fn-coffee').evaluate(e=>e===document.activeElement),true);
  await p.setViewportSize({width:390,height:844});await p.emulateMedia({colorScheme:'dark'});await p.locator('#fn-coffee').click();
  assert(await p.locator('#fn-coffee-dialog').evaluate(e=>e.scrollWidth<=e.clientWidth));await p.screenshot({path:out+'/coffee-mobile.png'});
  await p.getByRole('button',{name:'关闭打赏窗口'}).click();assert.equal(await p.locator('#fn-coffee-dialog').isVisible(),false);
  await p.goto(base+'/');assert.equal(await p.locator('#fn-coffee').count(),0);
  await p.goto(base+'/haloflux.html');assert.equal(await p.locator('#fn-coffee').count(),0);
  await p.goto(base+'/remote.html');assert.equal(await p.locator('#fn-coffee').count(),0);
  await ctx.addCookies((await ctx.cookies(base)).map(c=>({...c,domain:'nas.preview.test'})));
  await p.goto(remote+'/#/settings');await p.locator('#fn-coffee').waitFor();
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('PASS: authenticated fixed QR assets; no upload; lazy display; desktop/mobile; Esc/close/focus; hidden on HDMI/HALOFLUX/VNC; remote dashboard entry.');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
