/* Fixed, local support assets. No configuration or upload endpoint. */
(()=>{'use strict';
 const local=['localhost','127.0.0.1','[::1]'].includes(location.hostname);
 // Never overlay the NAS HDMI dashboard or the animation/remote-control screens.
 if(!['/','/index.html','/launcher.html'].includes(location.pathname))return;
 if(local&&location.pathname!=='/launcher.html')return;
 const style=document.createElement('link');style.rel='stylesheet';style.href='/coffee/coffee.css';document.head.append(style);
 const button=document.createElement('button');button.id='fn-coffee';button.type='button';button.textContent='☕ 请作者喝一杯咖啡';button.setAttribute('aria-haspopup','dialog');
 const dialog=document.createElement('dialog');dialog.id='fn-coffee-dialog';dialog.setAttribute('aria-labelledby','fn-coffee-title');
 dialog.innerHTML='<header><div><h2 id="fn-coffee-title">请作者喝一杯咖啡</h2><p>感谢你支持汪同学的开发与维护。</p></div><button type="button" aria-label="关闭打赏窗口" autofocus>×</button></header><div class="fn-coffee-codes"></div><p class="fn-coffee-note">自愿支持，不影响任何功能的使用。请核对收款人后再付款。</p>';
 const codes=dialog.querySelector('.fn-coffee-codes');
 let loaded=false;
 button.addEventListener('click',()=>{
  if(!loaded){
   for(const [label,url,width,height] of [['支付宝','/coffee/alipay.png',912,912],['微信','/coffee/wechat.png',658,658]]){
    const figure=document.createElement('figure'),caption=document.createElement('figcaption'),img=document.createElement('img');
    caption.textContent=label;img.alt='汪同学的'+label+'收款码';img.src=url;img.width=width;img.height=height;img.decoding='async';
    figure.append(caption,img);codes.append(figure);
   }
   loaded=true;
  }
  dialog.showModal();
 });
 dialog.querySelector('button').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
 document.body.append(button,dialog);
})();
