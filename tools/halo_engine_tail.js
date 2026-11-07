// fnMonitor adapter. All signal inputs are normalized, bounded real telemetry.
let target={},smooth={},live=false,fps=24,quality='economy',last=0,ready=false,frames=0,fpsAt=0,measured=0;
const unitSignal=v=>Math.max(0,Math.min(1,Number.isFinite(v)?v:0));
function setTelemetry(input,settings={}){
 target={...input};live=input.live===true;fps=[15,24,30].includes(settings.fps)?settings.fps:24;
 const q=settings.quality==='balanced'?'balanced':'economy';
 if(q!==quality){quality=q;resize();}
}
function mapSignals(dt){
 for(const k of ['cpu','gpu','cpuHeat','gpuHeat','mem','vram','storage','read','write','rx','tx','power']){
  const val=live?unitSignal(target[k]):0;smooth[k]=(smooth[k]||0)+(val-(smooth[k]||0))*(1-Math.exp(-dt*1.8));
 }
 const v=smooth;
 C.tempo=.45+.9*v.cpu+.3*v.gpu;C.ringSpeed=.12+1.9*v.cpu;
 C.runnerSpeed=.3+1.8*v.gpu+.8*v.read;C.cometSpeed=.5+1.5*v.read;
 C.cometPerBeat=.2+1.8*v.write;C.cometBurst=.6+3*v.write;
 C.flyerSpeed=.4+2*v.rx;C.burstRate=.2+1.8*v.tx;C.burstSize=.5+v.tx;
 C.runnerCount=Math.round((quality==='balanced'?120:70)+80*v.mem+50*v.vram);
 C.rimBright=.5+.9*v.storage;C.dataFlicker=.2+v.read+v.write;
 C.glow=.4+v.power;C.beamBright=.6+.8*v.power;C.beamLen=.45+.7*v.rx;
}
function drawTelemetryArcs(){
 if(!live)return;
 camT(S,DPR);S.save();S.translate(cx,cy);S.globalCompositeOperation='lighter';
 const heat=Math.max(smooth.cpuHeat||0,smooth.gpuHeat||0),hot=heat>.85;
 const specs=[['mem',.93,hot?'#ff704d':'#77e3dc'],['storage',.89,(smooth.storage||0)>.9?'#ffab58':'#9abbe8'],['vram',.85,'#c9a4ff']];
 for(const [key,r,col] of specs){
  if(target[key]==null)continue;
  S.lineWidth=2.3;S.strokeStyle=col;S.globalAlpha=.65;
  S.beginPath();S.arc(0,0,R*r,-thV,-thV+2*thV*(smooth[key]||0));S.stroke();
 }
 if(heat>.6){
  const g=S.createRadialGradient(0,0,R*.2,0,0,R);g.addColorStop(0,'transparent');
  g.addColorStop(1,hot?'rgba(255,75,50,.14)':'rgba(255,175,80,.08)');
  S.fillStyle=g;S.globalAlpha=unitSignal((heat-.6)/.4);S.beginPath();S.arc(0,0,R,0,TAU);S.fill();
 }
 S.restore();S.globalAlpha=1;S.globalCompositeOperation='source-over';
}
function resize(){
 const rect=stage.getBoundingClientRect();if(rect.width<20||rect.height<20)return;
 DPR=Math.min(devicePixelRatio||1,quality==='balanced'?1.5:1);
 resizeStage();ready=true;
}
function frame(now){
 requestAnimationFrame(frame);
 if(document.hidden||!ready){last=now;return;}
 const cap=live&&target.cpu>.85?Math.min(fps,12):fps;
 if(now-last<1000/cap)return;
 const dt=Math.min(.1,(now-last)/1000);last=now;T+=dt;
 mapSignals(dt);drawStage(dt);frames++;
 if(now-fpsAt>1500){measured=Math.round(frames*1000/(now-fpsAt));frames=0;fpsAt=now;}
}
let resizeTimer;new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(resize,160)}).observe(stage);
window.HaloEngine={setTelemetry,stats:()=>({fps:measured,limited:live&&target.cpu>.85,live,parameters:{...C},signals:{...smooth}})};
resize();requestAnimationFrame(frame);
})();
