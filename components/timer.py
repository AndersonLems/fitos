"""Cronômetro de descanso executado no navegador (não provoca recarga da página)."""
from __future__ import annotations

import streamlit.components.v1 as components

from components.ui import theme


def rest_timer(default_seconds: int = 90, key: str = "t") -> None:
    c = theme()
    components.html(f"""
<div id="w{key}" style="font-family:Inter,system-ui,sans-serif;color:{c['ink']};background:{c['surface']};border:1px solid {c['border']};
  border-radius:12px;padding:10px 14px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
  <div style="font-size:12.5px;color:{c['ink2']}">Descanso</div>
  <div id="d{key}" style="font-family:'Space Grotesk',system-ui,sans-serif;font-weight:800;font-size:30px;min-width:84px">
    {default_seconds // 60}:{default_seconds % 60:02d}</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button data-s="60">60 s</button><button data-s="90">90 s</button><button data-s="120">2 min</button>
    <button data-s="180">3 min</button><button id="x{key}">parar</button>
  </div>
</div>
<style>button{{background:{c['chip']};color:{c['ink']};border:1px solid {c['border']};border-radius:6px;min-height:36px;padding:5px 10px;cursor:pointer;font:inherit;font-size:13px}}
button:hover{{border-color:{c['accent']}}}</style>
<script>
let t=null,left={default_seconds};const d=document.getElementById('d{key}');
function show(){{d.textContent=Math.floor(left/60)+':'+String(left%60).padStart(2,'0');d.style.color=left<=5?'{c['bad']}':'{c['ink']}';}}
function beep(){{try{{const c=new AudioContext(),o=c.createOscillator();o.connect(c.destination);o.frequency.value=880;o.start();setTimeout(()=>o.stop(),400);}}catch(e){{}}
 if(navigator.vibrate)navigator.vibrate([200,100,200]);}}
document.querySelectorAll('button[data-s]').forEach(b=>b.onclick=()=>{{left=+b.dataset.s;show();clearInterval(t);
 t=setInterval(()=>{{left--;show();if(left<=0){{clearInterval(t);beep();}}}},1000);}});
document.getElementById('x{key}').onclick=()=>{{clearInterval(t);}};
</script>""", height=140)
