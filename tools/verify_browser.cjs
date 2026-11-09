const {chromium}=require(process.env.PW_PATH),fs=require('fs'),assert=require('node:assert/strict');
(async()=>{const cfg=JSON.parse(fs.readFileSync(process.argv[2])),base='http://127.0.0.1:'+cfg.port;
const b=await chromium.launch({executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',headless:true,args:['--no-sandbox']});
try{const ctx=await b.newContext(),p=await ctx.newPage(),err=[];p.on('pageerror',e=>err.push(e.message));
const r=await ctx.request.post(base+'/api/auth/setup',{headers:{'X-FNM-Request':'1'},data:{password:require('crypto').randomBytes(20).toString('hex')}});assert((await r.json()).ok);
await p.goto(base+'/remote.html');await p.getByText('已连接 · 可以用鼠标和键盘操作').waitFor({timeout:10000});
// Framebuffer scaling must follow both wrapping toolbar and viewer resizes.
for(const [width,height] of [[1280,720],[1920,1080],[800,1280],[1024,600]]){
 await p.setViewportSize({width,height});await p.waitForTimeout(150);
 const layout=await p.evaluate(()=>{const c=document.querySelector('canvas').getBoundingClientRect(),s=document.getElementById('screen').getBoundingClientRect();return {cw:c.width,ch:c.height,sw:s.width,sh:s.height,left:c.left-s.left,top:c.top-s.top}});
 assert(Math.abs(layout.cw/layout.ch-4/3)<.01);assert(layout.cw<=layout.sw+1&&layout.ch<=layout.sh+1);
 assert(Math.abs(layout.left-(layout.sw-layout.cw)/2)<2);assert(Math.abs(layout.top-(layout.sh-layout.ch)/2)<2);
}
await p.setViewportSize({width:1280,height:900});await p.waitForTimeout(150);
let canvas=p.locator('canvas');await canvas.click({position:{x:100,y:100}});await p.keyboard.press('a');await p.waitForTimeout(300);
let ev=JSON.parse(fs.readFileSync(cfg.dir+'/events.json'));assert(ev.some(x=>x[0]=='key'&&x[1]==1&&x[2]==97));assert(ev.some(x=>x[0]=='mouse'&&x[1]==1));
const pixel=await canvas.evaluate(c=>Array.from(c.getContext('2d').getImageData(20,20,1,1).data));assert.deepEqual(pixel.slice(0,3),[80,140,40]);
let fitCalls=0;const fitActions=[];
await p.route('**/api/display/action',async route=>{const data=route.request().postDataJSON();if(!['fit_display_auto','fit_display_1080','fit_display_720'].includes(data.action))return route.continue();fitCalls++;fitActions.push(data.action);await route.fulfill({json:{ok:true,message:'已适配 HDMI 屏幕：1920 × 1080。'}})});
await p.getByRole('button',{name:'适配 HDMI 屏幕',exact:true}).click();await p.waitForTimeout(150);assert.equal(fitCalls,1);assert((await p.locator('#notice').textContent()).includes('1920 × 1080'));
for(const mode of ['1080','720']){await p.locator('#resolution').selectOption(mode);await p.locator('#fitHdmi').click();await p.waitForTimeout(100)}
assert.deepEqual(fitActions,['fit_display_auto','fit_display_1080','fit_display_720']);
await p.getByRole('button',{name:'一屏总览',exact:true}).click();
await p.getByRole('button',{name:'普通页面',exact:true}).click();
await p.getByRole('button',{name:'页面 −',exact:true}).click();
await p.getByRole('button',{name:'页面 ＋',exact:true}).click();
await p.getByRole('button',{name:'重置缩放',exact:true}).click();
await p.waitForTimeout(300);ev=JSON.parse(fs.readFileSync(cfg.dir+'/events.json'));
for(const k of [0xffc5,0xffc6,0xffe3,0x2d,0x3d,0x30])assert(ev.some(x=>x[0]=='key'&&x[1]==1&&x[2]==k),'missing key '+k);
await p.getByRole('button',{name:'纯画面全屏',exact:true}).click();
await p.waitForTimeout(300);assert(await p.locator('header').isHidden());
assert(await p.locator('#screen').evaluate(e=>Math.abs(e.getBoundingClientRect().height-innerHeight)<2));
await p.getByRole('button',{name:'显示控制栏',exact:true}).click();assert(await p.locator('header').isVisible());
if(await p.evaluate(()=>!!document.fullscreenElement))await p.evaluate(()=>document.exitFullscreen());
console.log('PASS: one-screen/normal/zoom keys delivered over real RFB; fullscreen removes toolbar and fills viewport; controls recover');
const q=await ctx.newPage();const qe=[];q.on('pageerror',e=>qe.push(e.message));
await q.route('**/api/overview',async route=>{const res=await route.fetch(),data=await res.json();Object.assign(data,{cpu:{percent:21,cores:6,frequency_mhz:3800,load:[1.16]},mem:{percent:44,used:3.2*2**30,total:7.3*2**30,available:4.1*2**30},disk_size:5.43*2**40,disk_used:4.99*2**40,disk_total:92,power:{ok:true,total:107.5,source:'rapl'},temp:{cpu:46,system:38},net:[{iface:'eth0',rx_speed:234*1024,tx_speed:80*1024}]});data.system.hostname='预览 NAS（示例）';await route.fulfill({json:data});});
await q.goto(base+'/');await q.locator('[data-m="pwr"]').waitFor({state:'attached'});
await q.keyboard.press('F8');
for(const [width,height] of [[1366,768],[1280,720],[1920,1080],[1024,600],[1080,1920],[3840,2160]]){
 await q.setViewportSize({width,height});await q.waitForTimeout(500);
 assert(await q.locator('#topbar').isHidden());
 const boxes=await q.locator('.metrics .metric').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom}}));
 assert.equal(boxes.length,6);
 for(const rect of boxes){assert(rect.left>=-1&&rect.right<=width+1&&rect.top>=0&&rect.bottom<=height,JSON.stringify({width,height,rect}));}
 assert(boxes[5].bottom>height*.85,'too much unused vertical space '+JSON.stringify({width,height,box:boxes[5]}));
 if(width===1366){const path=require('path');const out=path.resolve(__dirname,'../validation');fs.mkdirSync(out,{recursive:true});await q.screenshot({path:out+'/one-screen-1366.png'});}
}
await q.reload();await q.waitForTimeout(600);assert(await q.locator('#topbar').isHidden());
await q.keyboard.press('F9');assert(await q.locator('#topbar').isVisible());
await q.reload();await q.waitForTimeout(500);assert(await q.locator('#topbar').isVisible());
assert.deepEqual(qe,[]);await q.close();
console.log('PASS: real dashboard all six metric cards fit six viewport sizes including portrait and 4K, navigation hidden, saved choice restored, ordinary mode recovered');
assert.deepEqual(err,[]);await ctx.request.post(base+'/api/auth/logout',{headers:{'X-FNM-Request':'1'},data:{}});await p.getByText('连接已断开，请确认已登录且远程控制已启动，再重新连接。').waitFor({timeout:7000});
console.log('PASS: real noVNC rendered RFB pixels, delivered mouse click and key, disconnected on logout');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
