/* Only the NAS-local Chromium follows the shared HDMI scene choice. Other clients stay put. */
(()=>{'use strict';
 const local=['127.0.0.1','localhost','[::1]'].includes(location.hostname);
 if(!local||window.top!==window)return;
 // Shared by the monitor and HALOFLUX on the HDMI browser, including VNC input.
 // Override interactive elements too, so a pointer parked on a button disappears.
 const cursorStyle=document.createElement('style');
 cursorStyle.textContent='html.fnm-cursor-idle,html.fnm-cursor-idle *,html.fnm-cursor-idle *::before,html.fnm-cursor-idle *::after{cursor:none!important}';
 document.head.append(cursorStyle);
 let cursorTimer;
 function wakeCursor(){
  clearTimeout(cursorTimer);
  document.documentElement.classList.remove('fnm-cursor-idle');
  if(!document.hidden)cursorTimer=setTimeout(()=>document.documentElement.classList.add('fnm-cursor-idle'),5000);
 }
 for(const event of ['pointermove','pointerdown','wheel'])addEventListener(event,wakeCursor,{capture:true,passive:true});
 document.addEventListener('visibilitychange',wakeCursor);
 addEventListener('pageshow',wakeCursor);
 addEventListener('pagehide',()=>clearTimeout(cursorTimer));
 wakeCursor();
 const current=location.pathname==='/haloflux.html'?'haloflux':'monitor';
 let stopped=false;
 addEventListener('pagehide',()=>{stopped=true});
 async function poll(){
  if(stopped)return;
  try{
   const r=await fetch('/api/display/scene',{cache:'no-store',signal:AbortSignal.timeout(4000)});
   if(r.ok){const s=await r.json();
    if(['monitor','haloflux'].includes(s.mode)&&s.mode!==current){location.replace(s.mode==='haloflux'?'/haloflux.html':'/#/overview');return;}
    await fetch('/api/display/scene/seen',{method:'POST',headers:{'Content-Type':'application/json','X-FNM-Request':'1'},body:JSON.stringify({mode:current}),signal:AbortSignal.timeout(4000)});
   }
  }catch{}
  if(!stopped)setTimeout(poll,3000);
 }
 poll();
})();
