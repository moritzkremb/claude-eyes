"""Interactive single-file viewer for one indexed video: see what the agent sees, synced to the real video."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .common import read_json


def build(vdir: Path) -> Path:
    src, meta = read_json(vdir / "source.json"), read_json(vdir / "meta.json")
    shots = (read_json(vdir / "shots.json", {}) or {}).get("shots", [])
    ocr = read_json(vdir / "ocr.json", {}) or {}
    trn = read_json(vdir / "transcript.json", {}) or {}
    audio = read_json(vdir / "audio.json", {}) or {}
    color = read_json(vdir / "color.json", {}) or {}

    def rel(path: str | None) -> str | None:
        if not path:
            return None
        try:
            return Path(os.path.relpath(path, vdir)).as_posix()
        except ValueError:
            return Path(path).as_uri()

    duration = meta["duration"] or 1
    data = {
        "title": src.get("title") or src["id"], "id": src["id"], "source": src.get("url") or src.get("source"),
        "video": rel(str(Path(src["media"]).resolve())), "videoAbs": Path(src["media"]).resolve().as_uri(),
        "duration": duration, "fps": meta.get("fps") or 30,
        "w": meta.get("width"), "h": meta.get("height"),
        "shots": [{"s": s["start"], "e": s["end"], "f": rel(s.get("frame"))} for s in shots],
        "spans": [{"s": s["start"], "e": s["end"], "t": s["text"], "b": s["box"]} for s in ocr.get("spans", [])[:4000]],
        "engine": ocr.get("engine"),
        "segs": [{"s": s["start"], "e": s["end"], "t": s["text"], "k": s.get("speaker")} for s in trn.get("segments", [])],
        "words": [[w["start"], w["end"], w["text"]] for w in trn.get("word_timings") or []],
        "events": trn.get("events", []), "speakers": trn.get("speakers") or [], "tsource": trn.get("source"),
        "curve": audio.get("curve", [])[:: max(1, len(audio.get("curve", [])) // 1500)],
        "lufs": audio.get("lufs"), "palette": color.get("colors", []),
        "cpm": round(max(0, len(shots) - 1) * 60 / duration, 1),
    }
    out = vdir / "view.html"
    out.write_text(TEMPLATE.replace("/*__DATA__*/", "const D = " + json.dumps(data, ensure_ascii=False) + ";"),
                   encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>eyes · view</title>
<style>
:root{--bg:#0c0d10;--panel:#14161b;--line:#252832;--ink:#e9e7e1;--dim:#8a8f9c;--y:#ffd23f;--r:#ff5a3c;--c:#6fd3ff;--g:#8be28b}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
header{display:flex;gap:16px;align-items:center;padding:12px 18px;border-bottom:1px solid var(--line);flex-wrap:wrap}
header h1{font-size:16px;margin:0;font-weight:650;max-width:40vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{font-size:11.5px;padding:3px 8px;border:1px solid var(--line);border-radius:99px;color:var(--dim)}
.chip b{color:var(--ink);font-weight:600}.pal{display:flex;height:18px;width:120px;border-radius:4px;overflow:hidden}
#q{margin-left:auto;background:var(--panel);border:1px solid var(--line);color:var(--ink);padding:8px 12px;border-radius:8px;width:260px;font-size:14px}
main{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:14px;padding:14px 18px;height:calc(100vh - 62px - 230px)}
.stage{position:relative;background:#000;border-radius:10px;overflow:hidden;display:flex;align-items:center;justify-content:center;min-height:0}
video{max-width:100%;max-height:100%;display:block}
#ov{position:absolute;pointer-events:none}
.hud{position:absolute;left:10px;top:10px;display:flex;gap:6px}.hud span{background:#000a;border:1px solid #fff2;padding:3px 8px;border-radius:6px;font-size:12px}
#cutflash{position:absolute;inset:0;border:4px solid var(--r);opacity:0;pointer-events:none;transition:opacity .25s}
.side{display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--line);border-radius:10px;min-height:0}
.tabs{display:flex;border-bottom:1px solid var(--line)}.tabs button{flex:1;background:none;border:0;color:var(--dim);padding:10px;cursor:pointer;font-size:13px}
.tabs button.on{color:var(--ink);box-shadow:inset 0 -2px var(--y)}
.pane{overflow:auto;padding:10px 12px;flex:1;display:none}.pane.on{display:block}
.seg{padding:5px 6px;border-radius:6px;cursor:pointer}.seg:hover{background:#ffffff08}.seg.cur{background:#ffd23f14}
.seg .t,.row .t{color:var(--dim);font-size:11px;margin-right:6px}.w{border-radius:3px}.w.cur{background:var(--y);color:#000}
.row{padding:6px;border-bottom:1px solid var(--line);cursor:pointer}.row:hover{background:#ffffff08}
.tag{font-size:10px;padding:1px 6px;border-radius:4px;margin-right:6px}.said{background:#ffd23f22;color:var(--y)}.shown{background:#6fd3ff22;color:var(--c)}.heard{background:#8be28b22;color:var(--g)}
mark{background:var(--y);color:#000;border-radius:2px}
footer{padding:0 18px 12px}
.ctrl{display:flex;gap:6px;align-items:center;margin:4px 0 8px}.ctrl button{background:var(--panel);border:1px solid var(--line);color:var(--ink);padding:5px 10px;border-radius:6px;cursor:pointer;font-size:12px}
.ctrl label{font-size:12px;color:var(--dim);display:flex;gap:4px;align-items:center;margin-left:8px}.ctrl .keys{margin-left:auto;color:var(--dim);font-size:11.5px}
#tl{width:100%;height:120px;display:block;background:var(--panel);border:1px solid var(--line);border-radius:8px;cursor:crosshair}
#strip{display:flex;gap:3px;overflow-x:auto;margin-top:8px;padding-bottom:4px}#strip img{height:56px;border-radius:3px;opacity:.55;cursor:pointer;border:2px solid transparent}
#strip img.cur{opacity:1;border-color:var(--y)}
#tip{position:fixed;pointer-events:none;background:#000d;border:1px solid var(--line);padding:4px 8px;border-radius:6px;font-size:12px;display:none;z-index:9}
</style></head><body>
<header><h1 id="title"></h1><div class="chips" id="chips"></div><div class="pal" id="pal"></div>
<input id="q" placeholder="Search said, shown, heard…  ( / )" autocomplete="off"></header>
<main>
 <div class="stage" id="stage"><video id="v" preload="auto" playsinline></video><canvas id="ov"></canvas><div id="cutflash"></div>
  <div class="hud mono"><span id="tc">0:00.0</span><span id="shotn"></span></div></div>
 <div class="side"><div class="tabs"><button data-p="ptr" class="on">Said</button><button data-p="pos">Shown</button><button data-p="pres">Search</button></div>
  <div class="pane on" id="ptr"></div><div class="pane" id="pos"></div><div class="pane" id="pres"><div style="color:var(--dim)">Type in the search box.</div></div></div>
</main>
<footer>
 <div class="ctrl"><button id="play">Play</button><button id="fb">◀ frame</button><button id="ff">frame ▶</button><button id="sb">◀ shot</button><button id="sf">shot ▶</button>
  <label><input type="checkbox" id="boxes" checked> text boxes</label><label><input type="checkbox" id="flash" checked> flash on cut</label>
  <span class="keys mono">space play · ←/→ frame · ,/. shot · / search</span></div>
 <canvas id="tl"></canvas><div id="strip"></div>
</footer><div id="tip" class="mono"></div>
<script>
/*__DATA__*/
const $=s=>document.querySelector(s), v=$('#v'), ov=$('#ov'), tl=$('#tl');
const fmt=t=>{t=Math.max(0,t);const m=Math.floor(t/60),s=t-m*60;return m+':'+(s<10?'0':'')+s.toFixed(1)};
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const cuts=D.shots.slice(1).map(s=>s.s), spk={}; D.speakers.forEach((s,i)=>spk[s]='S'+(i+1));
v.src=D.video; v.onerror=()=>{if(v.src!==D.videoAbs&&location.protocol==='file:'){v.src=D.videoAbs;return}$('#stage').insertAdjacentHTML('beforeend','<div style="position:absolute;color:#f99;padding:20px;text-align:center">Video not found at<br><span class=mono>'+esc(decodeURI(D.video))+'</span><br>Re-index it, or open this file from your own computer.</div>')};
$('#title').textContent=D.title; document.title='eyes · '+D.title;
const chip=(k,val)=>val==null?'':`<span class="chip">${k} <b>${esc(val)}</b></span>`;
$('#chips').innerHTML=chip('length',fmt(D.duration))+chip('size',D.w+'×'+D.h)+chip('shots',D.shots.length)+chip('cuts/min',D.cpm)+chip('LUFS',D.lufs)
 +chip('said',D.tsource||'none')+chip('shown',D.engine||'none')+(D.words.length?chip('word timings','yes'):'');
$('#pal').innerHTML=D.palette.map(c=>`<div title="${c.hex}" style="flex:${c.share};background:${c.hex}"></div>`).join('');
// transcript with word-level spans
const segEls=[], wordEls=[];
$('#ptr').innerHTML=D.events.map(e=>`<div class="seg" data-t="${e.start}"><span class="t mono">${fmt(e.start)}</span><span class="tag heard">heard</span>${esc(e.text)}</div>`).join('');
let wi=0;
D.segs.forEach((s,i)=>{const el=document.createElement('div');el.className='seg';el.dataset.t=s.s;
 let html=`<span class="t mono">${fmt(s.s)}</span>`+(D.speakers.length>1&&s.k?`<b style="color:var(--c)">${spk[s.k]}:</b> `:'');
 const ws=[];while(wi<D.words.length&&D.words[wi][0]<s.e+0.25){if(D.words[wi][0]>=s.s-0.3)ws.push(wi);wi++}
 html+=ws.length?ws.map(j=>`<span class="w" data-w="${j}">${esc(D.words[j][2])}</span>`).join(' '):esc(s.t);
 el.innerHTML=html;$('#ptr').appendChild(el);segEls.push(el)});
document.querySelectorAll('.w').forEach(el=>wordEls[+el.dataset.w]=el);
$('#pos').innerHTML=D.spans.slice().sort((a,b)=>a.s-b.s).map(s=>`<div class="row" data-t="${s.s}"><span class="t mono">${fmt(s.s)}</span>${esc(s.t)}</div>`).join('')||'<div style="color:var(--dim)">No on-screen text read.</div>';
document.addEventListener('click',e=>{const w=e.target.closest('.w');if(w){seek(D.words[+w.dataset.w][0]);return}
 const r=e.target.closest('[data-t]');if(r&&!e.target.closest('#strip'))seek(+r.dataset.t)});
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>tab(b.dataset.p));
function tab(p){document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.p===p));document.querySelectorAll('.pane').forEach(x=>x.classList.toggle('on',x.id===p))}
// search
$('#q').oninput=()=>{const q=$('#q').value.trim().toLowerCase();if(!q){tab('ptr');return}tab('pres');
 const re=new RegExp('('+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig');const hits=[];
 D.segs.forEach(s=>{if(s.t.toLowerCase().includes(q)){let t=s.s;const w=D.words.find(w=>w[0]>=s.s-0.3&&w[0]<=s.e+0.3&&w[2].toLowerCase().includes(q.split(' ')[0]));if(w)t=w[0];hits.push(['said',t,s.t])}});
 D.spans.forEach(s=>{if(s.t.toLowerCase().includes(q))hits.push(['shown',s.s,s.t])});
 D.events.forEach(e=>{if(e.text.toLowerCase().includes(q))hits.push(['heard',e.start,e.text])});
 hits.sort((a,b)=>a[1]-b[1]);
 $('#pres').innerHTML=`<div style="color:var(--dim);margin-bottom:6px">${hits.length} match${hits.length==1?'':'es'}</div>`+hits.map(h=>`<div class="row" data-t="${h[1]}"><span class="t mono">${fmt(h[1])}</span><span class="tag ${h[0]}">${h[0]}</span>${esc(h[2]).replace(re,'<mark>$1</mark>')}</div>`).join('');
 searchHits=hits;drawTL()};
let searchHits=[];
// shot strip
const strip=$('#strip');D.shots.forEach((s,i)=>{if(!s.f)return;const im=new Image();im.src=s.f;im.loading='lazy';im.title='#'+(i+1)+' '+fmt(s.s);im.dataset.i=i;im.onclick=()=>seek(s.s+0.01);strip.appendChild(im)});
const shotAt=t=>{let lo=0,hi=D.shots.length-1;while(lo<hi){const m=(lo+hi+1)>>1;if(D.shots[m].s<=t)lo=m;else hi=m-1}return lo};
// controls
function seek(t){v.currentTime=Math.max(0,Math.min(D.duration-0.01,t));tick(true)}
const step=d=>{v.pause();seek(v.currentTime+d/D.fps)}, shot=d=>{const i=shotAt(v.currentTime+0.01)+d;if(i>=0&&i<D.shots.length)seek(D.shots[i].s+0.01)};
$('#play').onclick=()=>v.paused?v.play():v.pause();v.onplay=v.onpause=()=>$('#play').textContent=v.paused?'Play':'Pause';
$('#fb').onclick=()=>step(-1);$('#ff').onclick=()=>step(1);$('#sb').onclick=()=>shot(-1);$('#sf').onclick=()=>shot(1);
document.addEventListener('keydown',e=>{if(e.target===$('#q')){if(e.key==='Escape')$('#q').blur();return}
 if(e.key===' '){e.preventDefault();$('#play').click()}else if(e.key==='ArrowLeft')step(-1);else if(e.key==='ArrowRight')step(1);
 else if(e.key===',')shot(-1);else if(e.key==='.')shot(1);else if(e.key==='/'){e.preventDefault();$('#q').focus()}});
// overlay
function placeOverlay(){const r=v.getBoundingClientRect(),p=$('#stage').getBoundingClientRect();ov.style.left=(r.left-p.left)+'px';ov.style.top=(r.top-p.top)+'px';
 ov.width=r.width*devicePixelRatio;ov.height=r.height*devicePixelRatio;ov.style.width=r.width+'px';ov.style.height=r.height+'px'}
function drawOverlay(t){const c=ov.getContext('2d'),W=ov.width,H=ov.height;c.clearRect(0,0,W,H);if(!$('#boxes').checked)return;
 c.lineWidth=2*devicePixelRatio;c.font=`${11*devicePixelRatio}px ui-monospace,Menlo,monospace`;
 D.spans.forEach(s=>{if(t<s.s||t>s.e)return;const[x,y,w,h]=s.b;c.strokeStyle='#6fd3ff';c.strokeRect(x*W,y*H,w*W,h*H);
  const label=s.t.length>40?s.t.slice(0,40)+'…':s.t,tw=c.measureText(label).width+8*devicePixelRatio;c.fillStyle='#000c';c.fillRect(x*W,Math.max(0,y*H-15*devicePixelRatio),tw,14*devicePixelRatio);
  c.fillStyle='#6fd3ff';c.fillText(label,x*W+4*devicePixelRatio,Math.max(11*devicePixelRatio,y*H-4*devicePixelRatio))})}
// timeline
const lanes=[['cuts',18],['said',18],['shown',30],['sound',30],['heard',10]];
function drawTL(){const dpr=devicePixelRatio,W=tl.clientWidth*dpr,H=tl.clientHeight*dpr;tl.width=W;tl.height=H;const c=tl.getContext('2d'),X=t=>t/D.duration*W;
 let y=6*dpr;const row=(h)=>{const r=y;y+=(h+4)*dpr;return r};c.font=`${10*dpr}px ui-monospace,Menlo,monospace`;
 const lab=(txt,yy)=>{c.fillStyle='#8a8f9c';c.fillText(txt,4*dpr,yy+10*dpr)};
 let r=row(18);D.shots.forEach((s,i)=>{c.fillStyle=i%2?'#2a2e38':'#1f222a';c.fillRect(X(s.s),r,Math.max(1,X(s.e)-X(s.s)),18*dpr)});
 c.fillStyle='#ff5a3c';cuts.forEach(t=>c.fillRect(X(t)-dpr,r,2*dpr,18*dpr));lab('cuts',r);
 r=row(18);c.fillStyle='#ffd23f88';D.segs.forEach(s=>c.fillRect(X(s.s),r+4*dpr,Math.max(1,X(s.e)-X(s.s)),10*dpr));lab('said',r);
 r=row(30);c.fillStyle='#6fd3ff66';D.spans.forEach(s=>c.fillRect(X(s.s),r+s.b[1]*26*dpr,Math.max(1,X(s.e)-X(s.s)),3*dpr));lab('shown',r);
 r=row(30);c.strokeStyle='#8be28b';c.lineWidth=dpr;c.beginPath();D.curve.forEach(([t,l],i)=>{const yy=r+30*dpr-Math.max(0,Math.min(1,(l+50)/45))*30*dpr;i?c.lineTo(X(t),yy):c.moveTo(X(t),yy)});c.stroke();lab('sound',r);
 r=row(10);c.fillStyle='#8be28b';D.events.forEach(e=>c.fillRect(X(e.start),r,Math.max(2*dpr,X(e.end)-X(e.start)),8*dpr));
 c.fillStyle='#ffd23f';searchHits.forEach(h=>{c.beginPath();c.arc(X(h[1]),H-5*dpr,3*dpr,0,7);c.fill()});
 c.fillStyle='#fff';c.fillRect(X(v.currentTime)-dpr,0,2*dpr,H)}
let drag=false;const tlT=e=>(e.clientX-tl.getBoundingClientRect().left)/tl.clientWidth*D.duration;
tl.onpointerdown=e=>{drag=true;seek(tlT(e))};window.onpointerup=()=>drag=false;
tl.onpointermove=e=>{const t=tlT(e),tip=$('#tip');if(drag)seek(t);const i=shotAt(t);tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-30)+'px';
 const said=D.segs.find(s=>t>=s.s&&t<=s.e);tip.innerHTML=fmt(t)+' · shot #'+(i+1)+(said?'<br>'+esc(said.t.slice(0,60)):'')};
tl.onpointerleave=()=>$('#tip').style.display='none';
// sync loop
let lastShot=-1,lastSeg=-1,lastWord=-1;
function tick(force){const t=v.currentTime;$('#tc').textContent=fmt(t);const i=shotAt(t);$('#shotn').textContent='shot '+(i+1)+'/'+D.shots.length;
 if(i!==lastShot){if(lastShot>=0&&!v.paused&&$('#flash').checked&&i===lastShot+1){const f=$('#cutflash');f.style.opacity=1;setTimeout(()=>f.style.opacity=0,120)}
  strip.querySelectorAll('img').forEach(im=>im.classList.toggle('cur',+im.dataset.i===i));const cur=strip.querySelector('img.cur');if(cur)cur.scrollIntoView({block:'nearest',inline:'center'});lastShot=i}
 const si=D.segs.findIndex(s=>t>=s.s&&t<s.e+0.05);if(si!==lastSeg){segEls.forEach((el,j)=>el.classList.toggle('cur',j===si));if(si>=0)segEls[si].scrollIntoView({block:'nearest'});lastSeg=si}
 let w=-1;for(let j=0;j<D.words.length;j++){if(D.words[j][0]>t)break;if(t<=D.words[j][1]+0.05)w=j}
 if(w!==lastWord){if(wordEls[lastWord])wordEls[lastWord].classList.remove('cur');if(wordEls[w])wordEls[w].classList.add('cur');lastWord=w}
 drawOverlay(t);drawTL()}
v.addEventListener('loadedmetadata',()=>{placeOverlay();tick(true);const h=new URLSearchParams(location.hash.slice(1));
 if(h.get('q')){$('#q').value=h.get('q');$('#q').oninput()}if(h.get('t'))seek(parseFloat(h.get('t')))});window.addEventListener('resize',()=>{placeOverlay();tick(true)});
v.addEventListener('seeked',()=>tick(true));(function loop(){if(!v.paused)tick();requestAnimationFrame(loop)})();
drawTL();
</script></body></html>
"""
