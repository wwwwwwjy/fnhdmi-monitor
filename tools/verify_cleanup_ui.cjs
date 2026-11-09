// UI-only fixtures: never sends cleanup commands to a NAS.
const {chromium}=require(process.env.PW_PATH),fs=require('fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[],posts=[];
  let job=null,fail=false,offline=false;
  const status=()=>({control_requires_login:false,hdmi_running:true,display_vt:'tty4',active_vt:'tty4',integrated:true,hdmi_enabled:true,hdmi_managed:true,browser_installed:true,browser_running:true,job});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://fixture.test/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/launcher.html')return route.fulfill({contentType:'text/html',body:fs.readFileSync('app/www/launcher.html')});
   if(path==='/product-icon.png')return route.fulfill({contentType:'image/png',body:fs.readFileSync('app/www/product-icon.png')});
   if(path==='/api/display/status')return route.fulfill(offline?{status:503,json:{message:'fixture offline'}}:{json:status()});
   if(path==='/api/display/scene')return route.fulfill({json:{mode:'haloflux',connected:true,observed:'haloflux'}});
   if(path==='/api/display/action'){
    const body=route.request().postDataJSON();posts.push(body);
    if(body.action.startsWith('fit_display_')){job={action:body.action,state:'done',message:'已适配屏幕',elapsed:1,lines:[]};return route.fulfill({json:{ok:true,status:status()}})}
    assert.equal(body.action,'prepare_uninstall');assert.equal(body.background,true);
    assert.equal(route.request().headers()['x-fnm-request'],'1');
    job={action:'prepare_uninstall',state:'running',elapsed:1,lines:['[阶段] 清除显示自启','[阶段] 返回飞牛命令行'],stage:'返回飞牛命令行'};
    return route.fulfill({json:{ok:true,status:status()}});
   }
   return route.fulfill({status:404,body:''});
  });
  await page.goto('http://fixture.test/launcher.html');
  const cleanup=page.locator('#cleanupAll');await cleanup.waitFor();
  await page.waitForFunction(()=>!document.getElementById('cleanupAll').disabled);
  for(const [id,action] of [['fitAuto','fit_display_auto'],['fit1080','fit_display_1080'],['fit720','fit_display_720']]){await page.locator('#'+id).click();await page.waitForFunction(()=>!document.getElementById('fitAuto').disabled);assert.equal(posts.at(-1).action,action);assert.equal(posts.at(-1).background,true)}
  posts.length=0;job=null;
  await cleanup.click();assert.equal(posts.length,0);assert(await page.locator('#cleanupTaskArea #review').isVisible());
  await page.locator('#cancel').click();assert.equal(posts.length,0);
  await cleanup.click();await page.locator('#approve').click();
  await page.waitForFunction(()=>document.getElementById('taskTitle').textContent.includes('进行中'));
  assert.equal(posts.length,1);assert(await cleanup.isDisabled());assert(await page.locator('#env').isDisabled());assert(await page.locator('#fitAuto').isDisabled());
  assert(await page.locator('#cleanupTaskArea #task').isVisible());
  assert((await page.locator('#taskLog').textContent()).includes('返回飞牛命令行'));
  job={...job,state:'error',message:'清理未完成，请勿继续在应用商店卸载：fixture chvt failed'};
  await page.waitForFunction(()=>document.getElementById('taskTitle').textContent.includes('未完成'));
  assert(!(await cleanup.isDisabled()));assert(await page.locator('#copyCleanupLog').isVisible());
  await page.locator('#copyCleanupLog').click();
  assert((await page.locator('#toast').textContent()).includes('复制'));
  await cleanup.click();await page.locator('#approve').click();
  await page.waitForFunction(()=>document.getElementById('taskTitle').textContent.includes('进行中'));
  job={...job,state:'done',message:'清理完成，已返回飞牛命令行界面。现在请到飞牛应用商店卸载本软件。'};
  await page.waitForFunction(()=>document.getElementById('taskTitle').textContent.includes('已完成'));
  assert((await page.locator('#cleanupTaskArea').textContent()).includes('现在请到飞牛应用商店卸载'));
  assert(await page.locator('#taskBar').isHidden());
  await page.locator('#cleanupCard').screenshot({path:process.env.CLEANUP_SCREENSHOT||'/tmp/fnhdmi-302-build/cleanup-panel.png'});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  offline=true;
  await page.waitForFunction(()=>document.getElementById('hdmiState').textContent==='无法读取',{},{timeout:10000});
  assert(await cleanup.isDisabled());
  assert.deepEqual(errors,[]);
  console.log('PASS: cleanup confirmation/cancel, authenticated POST, live bottom progress, lock, failure, log copy, retry, success, mobile width and offline controls');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
