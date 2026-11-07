(()=>{'use strict';
 const $=id=>document.getElementById(id),MiB=1048576;
 const fields=[['cpu','CPU 占用','%'],['cpu_temp','CPU 温度','°C'],['gpu','GPU 占用','%'],['gpu_temp','GPU 温度','°C'],['memory','内存占用','%'],['vram','显存占用','%'],['disk_read','硬盘读取','B/s'],['disk_write','硬盘写入','B/s'],['net_rx','网络下载','B/s'],['net_tx','网络上传','B/s'],['storage','存储池占用','%'],['power','整机功耗','W']];
 const cards={};let latest=null,stopped=false,tipTimer;
 const valid=v=>typeof v==='number'&&Number.isFinite(v);
 const pct=(v,max)=>valid(v)&&valid(max)&&max>0?Math.min(1,Math.max(0,v/max)):null;
 const bytes=v=>{if(!valid(v))return '—';let i=0;const u=['B','KiB','MiB','GiB','TiB'];while(v>=1024&&i<4){v/=1024;i++}return v.toFixed(i?1:0)+' '+u[i]};
 function targets(data){
  if(!data||data.stale)return {live:false};const m=data.metrics||{},s=data.settings||{},v=k=>m[k]?.value;
  const scale=x=>x==null?null:Math.min(1,x*(s.intensity||1));
  return {live:true,cpu:pct(v('cpu'),100),gpu:pct(v('gpu'),100),cpuHeat:pct(v('cpu_temp'),s.cpu_hot),gpuHeat:pct(v('gpu_temp'),s.gpu_hot),mem:pct(v('memory'),100),vram:pct(v('vram'),100),storage:pct(v('storage'),100),read:scale(pct(v('disk_read'),s.read_mib*MiB)),write:scale(pct(v('disk_write'),s.write_mib*MiB)),rx:scale(pct(v('net_rx'),s.net_mib*MiB)),tx:scale(pct(v('net_tx'),s.net_mib*MiB)),power:scale(pct(v('power'),s.power_w))};
 }
 window.HaloMetrics={targets,bytes};
 for(const [key,label] of fields){
  const card=document.createElement('article');card.className='metric missing';card.dataset.metric=key;
  card.innerHTML='<div class="label"></div><div class="value">—</div><div class="source">等待采样</div><div class="bar"><i></i></div>';
  card.querySelector('.label').textContent=label;$('metrics').append(card);cards[key]=card;
 }
 function showTip(text){$('tip').textContent=text;$('tip').hidden=false;clearTimeout(tipTimer);tipTimer=setTimeout(()=>$('tip').hidden=true,5000)}
 async function api(url,data){
  const r=await fetch(url,{method:data?'POST':'GET',cache:'no-store',headers:data?{'Content-Type':'application/json','X-FNM-Request':'1'}:{},body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(5000)});
  if(r.status===401){location.href='/login.html?next=%2Fhaloflux.html';throw Error('登录已过期')}
  const j=await r.json();if(!r.ok)throw Error(j.error||j.message||'连接失败');return j;
 }
 function render(data){
  const m=data.metrics||{},s=data.settings||{};document.body.classList.toggle('offline',!!data.stale);
  for(const [key,label,unit] of fields){
   const item=m[key]||{},v=data.stale?null:item.value,ok=valid(v),card=cards[key];
   const max=key==='cpu_temp'?s.cpu_hot:key==='gpu_temp'?s.gpu_hot:key==='power'?s.power_w:key==='disk_read'?s.read_mib*MiB:key==='disk_write'?s.write_mib*MiB:key.startsWith('net_')?s.net_mib*MiB:100;
   card.classList.toggle('missing',!ok);card.classList.toggle('hot',ok&&(unit==='°C'||key==='storage')&&v>=max*.9);
   card.querySelector('.value').textContent=!ok?'—':unit==='B/s'?bytes(v)+'/s':v.toFixed(unit==='W'?1:0)+' '+unit;
   let detail=!ok?(data.stale?'采样已过期':item.reason||'不可用'):item.source||'';
   if(ok&&['memory','vram','storage'].includes(key))detail=bytes(m[key+'_used']?.value)+' / '+bytes(m[key+'_total']?.value)+(key==='vram'?' · '+(item.source||''):'');
   card.querySelector('.source').textContent=detail;card.title=label+' · '+detail;
   card.querySelector('.bar').hidden=!ok;card.querySelector('.bar i').style.width=(100*(pct(v,max)||0))+'%';
  }
  $('state').textContent=data.stale?'采样已过期 · 动效待机':'实时联动 · '+Math.round(data.age||0)+' 秒前采样 · 采集间隔约 '+data.interval+' 秒';
  window.HaloEngine?.setTelemetry(targets(data),s);
 }
 function offline(message){
  const d={...(latest||{}),stale:true};render(d);$('state').textContent=message+' · 动效待机';
 }
 async function poll(){
  if(stopped)return;
  if(!document.hidden){try{latest=await api('/api/display/telemetry');render(latest)}catch(e){offline(e.message)}}
  if(!stopped)setTimeout(poll,2000);
 }
 addEventListener('pagehide',()=>{stopped=true});
 setInterval(()=>{const s=window.HaloEngine?.stats();if(s)$('perf').textContent=(s.limited?'CPU 高负载 · 性能保护':latest?.settings?.quality==='balanced'?'均衡画质':'节能画质')+' · '+s.fps+' FPS · 环内纹理为视觉效果'},2000);
 function choices(name,items,label){
  const select=$('form').elements[name],chosen=latest.settings[name];select.replaceChildren(new Option(label,'auto'));
  for(const item of items)select.add(new Option(typeof item==='string'?item:item.name,typeof item==='string'?item:item.id));
  if(chosen!=='auto'&&!Array.from(select.options).some(o=>o.value===chosen))select.add(new Option(chosen+'（当前不可用）',chosen));
  select.value=chosen;
 }
 $('settings').onclick=()=>{if(!latest){showTip('等待采样连接后即可设置');return}
  choices('disk',latest.devices.disks,'物理盘合计');choices('net',latest.devices.nets,'自动：最忙网卡');choices('gpu',latest.devices.gpus,'自动：占用最高的 GPU');
  for(const [key,v] of Object.entries(latest.settings)){const el=$('form').elements[key];if(el)el.value=v}
  $('formMsg').textContent='';$('dialog').showModal();
 };
 $('close').onclick=()=>$('dialog').close();
 $('form').onsubmit=async e=>{e.preventDefault();const settings={};for(const [k,v] of new FormData(e.target))settings[k]=['disk','net','gpu','quality'].includes(k)?v:Number(v);
  const save=e.submitter;save.disabled=true;try{await api('/api/display/scene',{settings});$('dialog').close();latest=await api('/api/display/telemetry');render(latest);showTip('联动设置已保存')}catch(e){$('formMsg').textContent=e.message}finally{save.disabled=false}
 };
 $('monitor').onclick=async()=>{try{await api('/api/display/scene',{mode:'monitor'});location.href='/#/overview'}catch(e){showTip(e.message)}};
 $('pure').onclick=()=>{const on=document.body.classList.toggle('pure');$('pure').textContent=on?'显示数据':'纯动效'};
 $('full').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch{showTip('请使用浏览器全屏菜单')}};
 let idle;function wake(){document.body.classList.remove('idle');clearTimeout(idle);idle=setTimeout(()=>document.body.classList.add('idle'),5000)}
 addEventListener('pointermove',wake);addEventListener('keydown',wake);wake();poll();
})();
