"""Bundle the pitch deck slides into one static index.html (open locally or via GitHub Pages).

Usage: python3 pitch/deck/build.py
Keys: ← → / space to move, N to show speaker notes, F for full screen.
"""
import html
import json
from pathlib import Path

HERE = Path(__file__).parent
deck = json.loads((HERE / "deck.json").read_text())
slides = [(HERE / "slides" / f"{sid}.html").read_text() for sid in deck["order"]]
fonts = "\n".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck["faces"].values())

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(deck["title"])}</title>
{fonts}
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%;background:#0b1013;overflow:hidden}}
#stage{{position:absolute;left:50%;top:50%;width:1920px;height:1080px;transform-origin:center}}
#stage>section{{position:absolute;inset:0;width:1920px;height:1080px;display:none}}
#stage>section.on{{display:revert}}
#stage>section:not(.on){{display:none!important}}
table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;padding:18px 20px;border-bottom:1px solid #2C3A44}}
aside{{display:none}}
#notes{{position:fixed;left:0;right:0;bottom:0;max-height:40vh;overflow:auto;background:#000c;color:#eee;
  font:16px/1.5 system-ui,sans-serif;padding:16px 24px;white-space:pre-wrap;display:none}}
#hud{{position:fixed;right:12px;bottom:10px;font:12px system-ui,sans-serif;color:#9aa9b3;opacity:.7}}
</style></head><body>
<div id="stage">
{chr(10).join(slides)}
</div>
<div id="notes"></div>
<div id="hud"></div>
<script>
const S=[...document.querySelectorAll('#stage>section')],stage=document.getElementById('stage'),
notes=document.getElementById('notes'),hud=document.getElementById('hud');
let i=Math.max(0,S.findIndex(s=>'#'+s.id===location.hash));
function fit(){{const k=Math.min(innerWidth/1920,innerHeight/1080);stage.style.transform=`translate(-50%,-50%) scale(${{k}})`;}}
function show(n){{i=Math.max(0,Math.min(S.length-1,n));S.forEach((s,j)=>s.classList.toggle('on',j===i));
  const a=S[i].querySelector('aside');notes.textContent=a?a.textContent:'';
  hud.textContent=`${{i+1}} / ${{S.length}} · ← → · N notes · F full screen`;history.replaceState(null,'','#'+S[i].id);}}
addEventListener('keydown',e=>{{
  if(['ArrowRight','PageDown',' '].includes(e.key))show(i+1);
  else if(['ArrowLeft','PageUp'].includes(e.key))show(i-1);
  else if(e.key==='n'||e.key==='N')notes.style.display=notes.style.display==='block'?'none':'block';
  else if(e.key==='f'||e.key==='F')document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();
}});
addEventListener('click',e=>{{if(e.target.closest('#notes'))return;show(e.clientX>innerWidth/2?i+1:i-1);}});
addEventListener('resize',fit);fit();show(i);
</script></body></html>
"""
(HERE / "index.html").write_text(page)
print(f"wrote {HERE / 'index.html'} ({len(slides)} slides)")
