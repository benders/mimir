// The well on the home page (scripts/well.py, #68): turning it, edges and rings on two screen-sized canvases, and
// tracing a node's chain. Nodes are links placed by CSS for the first render; while turning, the nodes in view get
// their transform from here (CSS trig on every node costs ~4x more per frame). Data: <script id="well-data">.
// Past the "Up to" stage (<html data-max>, #77) nothing is placed, drawn or traced; it redraws when that changes.
(() => {
const well = document.querySelector('.well'), src = document.getElementById('well-data');
if (!well || !src) return;
const D=JSON.parse(src.textContent);
const cv=[...well.querySelectorAll('canvas')],cx=cv.map(c=>c.getContext('2d'));
const nodes=[...well.querySelectorAll('.node')].sort((a,b)=>a.dataset.n-b.dataset.n),lbs=nodes.map(a=>a.querySelector('.lb')),imgs=nodes.map(a=>a.querySelector('img[data-src]')),N=D.a.length,seen=new Float64Array(N).fill(NaN),KID=D.a.map(()=>[]),EDGES=[];
D.par.forEach((ps,c)=>ps.forEach(p=>{KID[p].push(c);EDGES.push([p,c])}));
const root=document.documentElement,lim=()=>root.dataset.max===undefined?99:+root.dataset.max;let MAX=lim();
let rot=0,R=348,TILT=44,W=0,dpr=1,on=null,up=null,down=null,queued=false;
function walk(n,m,s){for(const q of m[n])if(!s.has(q)&&D.c[q]<=MAX){s.add(q);walk(q,m,s)}return s}
function size(){W=well.clientWidth;R=W<600?W*.75:Math.min(440,W*.37);TILT=R/10;dpr=Math.min(devicePixelRatio||1,1.5);  // #76: two screen-sized canvases at 3x took ~24 MB

 well.style.setProperty('--R',R.toFixed(1));well.style.setProperty('--tilt',TILT.toFixed(1));seen.fill(NaN);
 for(const c of cv){c.width=Math.round(c.clientWidth*dpr);c.height=Math.round(c.clientHeight*dpr)}draw()}
function place(off,vh){  // the nodes in view (and a screen either side) that haven't been placed at this rotation
 for(let n=0;n<N;n++){if(seen[n]===rot||D.c[n]>MAX||D.y[n]<off-vh||D.y[n]>off+2*vh)continue;seen[n]=rot;
  const t=D.a[n]+rot,c=Math.cos(t),d=(c+1)/2,s=nodes[n].style,im=imgs[n];
  if(im&&!im.src)im.src=im.dataset.src;  // its icon, now that it is near the screen (#76)
  s.transform=`translate(${(R*Math.sin(t)).toFixed(1)}px,${(TILT*c).toFixed(1)}px) scale(${(.55+.45*d).toFixed(3)})`;
  s.opacity=(.35+.65*d).toFixed(3);s.zIndex=Math.round(100+99*c);s.pointerEvents=c<0?'none':'';  // behind the fog: not a target
  lbs[n].style.opacity=Math.min(1,Math.max(0,(c*R*D.k[n]-64)/8)).toFixed(2)}}
function draw(){queued=false;
 const off=cv[0].getBoundingClientRect().top-well.getBoundingClientRect().top,vh=cv[0].clientHeight,mid=W/2;place(off,vh);
 for(const g of cx){g.setTransform(dpr,0,0,dpr,0,-off*dpr);g.clearRect(0,off,W,vh)}
 for(const[i,y]of D.bands.entries()){if(i>MAX+1||y<off-TILT-10||y>off+vh+TILT+10)continue;  // rings: back half, front half
  for(const f of[0,1]){const g=cx[f];g.strokeStyle=D.col[Math.min(i,D.col.length-1)];g.globalAlpha=f?.35:.2;g.lineWidth=1;
   g.beginPath();g.ellipse(mid,y,R,TILT,0,f?0:Math.PI,f?Math.PI:2*Math.PI);g.stroke()}}
 const lit=[];
 for(const ed of EDGES){const[p,c]=ed;if(D.c[p]>MAX||D.c[c]>MAX)continue;const y0=D.y[p]+22,y1=D.y[c]-22;
  if(Math.max(y0,y1)<off-TILT||Math.min(y0,y1)>off+vh+TILT)continue;
  const hot=on&&(up.has(p)&&up.has(c)||down.has(p)&&down.has(c));/* on a path through it */if(hot){lit.push(ed);continue}edge(p,c,y0,y1,false)}
 for(const[p,c]of lit)edge(p,c,D.y[p]+22,D.y[c]-22,true)}
function edge(p,c,y0,y1,hot){  // along the cylinder's surface, a stroke per run on one side
 const a0=D.a[p]+rot,da=((D.a[c]-D.a[p]+Math.PI)%(2*Math.PI)+2*Math.PI)%(2*Math.PI)-Math.PI,S=12,pts=[];
 for(let k=0;k<=S;k++){const t=k/S,a=a0+da*t,y=y0+(y1-y0)*(3*t*t-2*t*t*t);
  pts.push([W/2+R*Math.sin(a),y+TILT*Math.cos(a),Math.cos(a)])}
 let s=0;for(let k=1;k<=S;k++)if(k==S||(pts[k+1][2]>=0)!=(pts[k][2]>=0)){
  const run=pts.slice(s,k+1),d=run.reduce((m,q)=>m+q[2],0)/run.length,g=cx[d>=0?1:0],dd=(d+1)/2;
  g.globalAlpha=hot?1:on?.04:.04+.26*dd*dd;g.lineWidth=hot?2.4:1.2;
  if(D.c[p]==D.c[c])g.strokeStyle=D.col[D.c[c]];
  else{const gr=g.createLinearGradient(0,y0,0,y1);gr.addColorStop(0,D.col[D.c[p]]);gr.addColorStop(1,D.col[D.c[c]]);g.strokeStyle=gr}
  g.beginPath();g.moveTo(run[0][0],run[0][1]);for(const q of run.slice(1))g.lineTo(q[0],q[1]);g.stroke();s=k}}
function later(){if(!queued){queued=true;requestAnimationFrame(draw)}}
function focus(n){up=n==null?null:walk(n,D.par,new Set([n]));down=n==null?null:walk(n,KID,new Set([n]));
 on=n==null?null:new Set([...up,...down]);
 well.classList.toggle('focus',!!on);for(const a of nodes)a.classList.toggle('on',!!on&&on.has(+a.dataset.n));later()}
// turning: horizontal drags (vertical ones scroll the page), then it coasts
let drag=null,moved=false,vel=0,touch=false;const still=matchMedia('(prefers-reduced-motion: reduce)');  // no coasting
well.addEventListener('pointerdown',ev=>{touch=ev.pointerType!='mouse';drag={x:ev.clientX,t:ev.timeStamp};moved=false;vel=0});
well.addEventListener('pointermove',ev=>{if(!drag)return;const dx=ev.clientX-drag.x;
 if(!moved){if(Math.abs(dx)<6)return;moved=true;well.setPointerCapture(ev.pointerId);well.classList.add('dragging')}
 rot+=dx/R;vel=dx/R/Math.max(8,ev.timeStamp-drag.t);drag={x:ev.clientX,t:ev.timeStamp};later()});
function release(){if(!drag)return;drag=null;well.classList.remove('dragging');
 if(moved&&!still.matches){let last=performance.now();(function coast(now){vel*=Math.pow(.995,now-last);rot+=vel*(now-last);last=now;draw();
  if(Math.abs(vel)>2e-5&&!drag)requestAnimationFrame(coast)})(last)}}
well.addEventListener('pointerup',release);well.addEventListener('pointercancel',()=>{drag=null;well.classList.remove('dragging')});
well.addEventListener('click',ev=>{if(moved){ev.preventDefault();moved=false;return}
 const a=ev.target.closest('.node');
 if(a&&touch&&!(on&&on.has(+a.dataset.n)&&a.classList.contains('tapped'))){  // touch: tap traces, a second tap opens
  ev.preventDefault();nodes.forEach(n=>n.classList.remove('tapped'));a.classList.add('tapped');focus(+a.dataset.n)}
 else if(!a)focus(null)});
well.addEventListener('pointerover',ev=>{const a=ev.target.closest('.node');if(ev.pointerType=='mouse'&&a&&!drag)focus(+a.dataset.n)});
well.addEventListener('pointerleave',ev=>{if(ev.pointerType=='mouse')focus(null)});
new MutationObserver(()=>{MAX=lim();focus(null)}).observe(root,{attributeFilter:['data-max']});
well.addEventListener('transitionend',later);  // the well eases to its new depth
addEventListener('scroll',later,{passive:true});addEventListener('resize',size);size();
})();
