#!/usr/bin/env python3
"""
Browser tool for hand-marking sketch page borders when automatic detection is off.

  python3 dev/sketch_correction/annotate.py --in tmp/sketches/originals \
      --work tmp/sketches/work --out tmp/sketches/out [--port 8766]

Open http://localhost:8766/ (forward the port if Cursor is remote). Pick a photo, trace the page
edge with the pencil (one closed loop, roughly following the paper's edge including its rounded
corners), press Submit. The server fits four edge curves to your stroke, dewarps and colour-matches
the page with correct_sketches.py, detects which corners were rounded, saves the stroke to
<work>/annotations.json and shows the result. Re-trace and resubmit as often as you like.

Batch re-run later with:  correct_sketches.py ... --corners tmp/sketches/work/annotations.json
"""
import argparse, glob, io, json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correct_sketches as cs

PREVIEW_W = 1400
lock = threading.Lock()

PAGE = r"""<!doctype html><meta charset=utf-8><title>Sketch border annotator</title>
<style>
 body{margin:0;font:14px system-ui;background:#1e1e1e;color:#ddd;display:grid;grid-template-columns:220px 1fr 1fr;height:100vh}
 #list{overflow:auto;border-right:1px solid #333}
 #list div{padding:8px 12px;cursor:pointer;border-bottom:1px solid #2a2a2a}
 #list div.sel{background:#3a3a3a} #list div.done::after{content:" ✓";color:#7c7}
 #left,#right{display:flex;flex-direction:column;min-width:0}
 .bar{padding:8px;display:flex;gap:8px;align-items:center;background:#252525;border-bottom:1px solid #333}
 button{background:#444;color:#eee;border:0;padding:6px 12px;border-radius:4px;cursor:pointer} button:hover{background:#555}
 button.primary{background:#2d6cdf} canvas{max-width:100%;max-height:calc(100vh - 44px);cursor:crosshair;touch-action:none}
 #result{max-width:100%;max-height:calc(100vh - 44px);object-fit:contain}
 #status{margin-left:auto;color:#aaa}
</style>
<div id=list></div>
<div id=left><div class=bar>
 <b id=title>–</b>
 <button onclick="clearStroke()">Clear</button>
 <label><input type=checkbox id=pencil onchange="const w=document.getElementById('warmth'); w.value=this.checked?0.5:1; document.getElementById('wv').textContent=w.value"> pencil page</label>
 <label title="how much to darken strokes; Submit re-runs">lines <input type=range id=lines min=0 max=1 step=0.05 value=0.5 style="width:110px;vertical-align:middle" oninput="document.getElementById('lv').textContent=this.value"> <span id=lv>0.5</span></label>
 <label title="paper tone: 0 = keep the photo's paper colour, 1 = full gallery cream">warmth <input type=range id=warmth min=0 max=1 step=0.05 value=1 style="width:110px;vertical-align:middle" oninput="document.getElementById('wv').textContent=this.value"> <span id=wv>1</span></label>
 <button class=primary onclick="submit()">Submit</button>
 <span id=status></span></div>
 <canvas id=c></canvas></div>
<div id=right><div class=bar><b>Result</b><span id=rinfo style="margin-left:12px;color:#aaa"></span></div><img id=result></div>
<script>
let names=[], cur=null, img=new Image(), stroke=[], drawing=false, scale=1, done={};
const cv=document.getElementById('c'), ctx=cv.getContext('2d');
async function init(){
  const r=await fetch('/api/list'); const j=await r.json(); names=j.names; done=j.done;
  const L=document.getElementById('list'); L.innerHTML='';
  names.forEach(n=>{const d=document.createElement('div'); d.textContent=n; d.id='li-'+n; if(done[n]) d.classList.add('done'); d.onclick=()=>load(n); L.appendChild(d)});
  if(names.length) load(names[0]);
}
function load(n){
  cur=n; document.querySelectorAll('#list div').forEach(d=>d.classList.toggle('sel',d.id==='li-'+n));
  document.getElementById('title').textContent=n; stroke=[]; document.getElementById('result').src='';
  document.getElementById('rinfo').textContent=''; document.getElementById('pencil').checked=false; document.getElementById('lines').value=0.5; document.getElementById('lv').textContent='0.5'; document.getElementById('warmth').value=1; document.getElementById('wv').textContent='1';
  img=new Image(); img.onload=()=>{cv.width=img.width; cv.height=img.height; scale=img.dataset?1:1; redraw();
     fetch('/api/get?name='+n).then(r=>r.json()).then(j=>{ document.getElementById('pencil').checked=!!j.pencil; if(j.warmth!=null){document.getElementById('warmth').value=j.warmth; document.getElementById('wv').textContent=j.warmth;} if(j.lines!=null){document.getElementById('lines').value=j.lines; document.getElementById('lv').textContent=j.lines;} if(j.border){ stroke=j.border.map(p=>[p[0]/j.scale, p[1]/j.scale]); redraw(); }
        if(j.result){ document.getElementById('result').src='/result/'+n+'.jpg?'+Date.now(); document.getElementById('rinfo').textContent=j.info||''; } });};
  img.src='/img/'+n;
}
function redraw(){ ctx.drawImage(img,0,0); if(stroke.length){ ctx.lineWidth=3; ctx.strokeStyle='#ff2bd6'; ctx.beginPath();
  stroke.forEach((p,i)=> i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1])); ctx.stroke(); } }
function pos(e){ const r=cv.getBoundingClientRect(); return [(e.clientX-r.left)*cv.width/r.width,(e.clientY-r.top)*cv.height/r.height]; }
cv.onpointerdown=e=>{drawing=true; stroke.push(pos(e)); redraw();};
cv.onpointermove=e=>{ if(!drawing) return; const p=pos(e), q=stroke[stroke.length-1]; if(Math.hypot(p[0]-q[0],p[1]-q[1])>2){stroke.push(p); redraw();} };
cv.onpointerup=cv.onpointerleave=()=>{drawing=false;};
function clearStroke(){stroke=[]; redraw();}
async function submit(){
  if(stroke.length<40){ alert('Trace the whole page edge first (one loop).'); return; }
  document.getElementById('status').textContent='processing…';
  const r=await fetch('/api/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,border:stroke,pencil:document.getElementById('pencil').checked,lines:parseFloat(document.getElementById('lines').value),warmth:parseFloat(document.getElementById('warmth').value)})});
  const j=await r.json(); document.getElementById('status').textContent=j.ok?'done':('error: '+j.error);
  if(j.ok){ document.getElementById('result').src='/result/'+cur+'.jpg?'+Date.now(); document.getElementById('rinfo').textContent=j.info;
    document.getElementById('li-'+cur).classList.add('done'); }
}
init();
</script>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/":
            return self.send(200, PAGE.encode())
        if u.path == "/api/list":
            ann = load_ann()
            return self.send(200, json.dumps({"names": list(FILES), "done": {n: True for n in ann}}).encode(), "application/json")
        if u.path == "/api/get":
            n = q.get("name", [""])[0]; a = load_ann().get(n)
            res = os.path.join(A.out, f"{n}.jpg")
            body = {"scale": SCALE.get(n, 1), "border": a["border"] if a else None, "pencil": a.get("pencil", False) if a else False, "lines": a.get("lines", 0.5) if a else 0.5, "warmth": a.get("warmth") if a else None,
                    "result": os.path.exists(res), "info": a.get("info", "") if a else ""}
            return self.send(200, json.dumps(body).encode(), "application/json")
        if u.path.startswith("/img/"):
            n = u.path[5:]
            if n not in FILES: return self.send(404, b"no")
            return self.send(200, preview(n), "image/jpeg")
        if u.path.startswith("/result/"):
            p = os.path.join(A.out, os.path.basename(u.path))
            if not os.path.exists(p): return self.send(404, b"no")
            return self.send(200, open(p, "rb").read(), "image/jpeg")
        self.send(404, b"not found")

    def do_POST(self):
        if self.path != "/api/submit":
            return self.send(404, b"no")
        n = int(self.headers.get("Content-Length", 0)); data = json.loads(self.rfile.read(n))
        name = data["name"]
        if name not in FILES:
            return self.send(400, json.dumps({"ok": False, "error": "unknown image"}).encode(), "application/json")
        sc = SCALE[name]
        border = [[x * sc, y * sc] for x, y in data["border"]]  # preview px -> photo px
        try:
            with lock:
                pencil = bool(data.get("pencil", False)); lines = float(data.get("lines", 0.5))
                warmth = data.get("warmth"); warmth = float(warmth) if warmth is not None else None
                ann = load_ann(); ann[name] = {"border": border, "pencil": pencil, "lines": lines, "warmth": warmth, "info": ann.get(name, {}).get("info", "")}
                json.dump(ann, open(ANN, "w"))          # save the stroke first, so a failed fit doesn't lose it
                import contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    cs.process(FILES[name], A.work, A.out, A.quality, border=border, pencil=pencil, lines=lines, warmth=warmth)
                info = buf.getvalue().strip().split("\n")[-1]
                ann[name]["info"] = info
                json.dump(ann, open(ANN, "w"))
            self.send(200, json.dumps({"ok": True, "info": info}).encode(), "application/json")
        except Exception as e:  # report to the page rather than dying
            import traceback; traceback.print_exc()
            self.send(200, json.dumps({"ok": False, "error": str(e)}).encode(), "application/json")


def preview(name):
    p = os.path.join(A.work, "annot", f"{name}.jpg")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        im = ImageOps.exif_transpose(Image.open(FILES[name])).convert("RGB")
        SCALE[name] = im.width / min(PREVIEW_W, im.width)
        im.thumbnail((PREVIEW_W, PREVIEW_W * 4)); im.save(p, quality=85)
    if name not in SCALE:
        full = ImageOps.exif_transpose(Image.open(FILES[name])); SCALE[name] = full.width / Image.open(p).width
    return open(p, "rb").read()


def load_ann():
    return json.load(open(ANN)) if os.path.exists(ANN) else {}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True); ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8766); ap.add_argument("--quality", type=int, default=82)
    A = ap.parse_args()
    os.makedirs(A.work, exist_ok=True); os.makedirs(A.out, exist_ok=True)
    FILES = {os.path.splitext(os.path.basename(f))[0]: f for f in sorted(glob.glob(os.path.join(A.inp, "*")))
             if f.lower().endswith((".heic", ".jpg", ".jpeg", ".png"))}
    SCALE = {}
    ANN = os.path.join(A.work, "annotations.json")
    for n in FILES: preview(n)  # warm the cache so SCALE is known before any submit
    print(f"{len(FILES)} photos. Open http://localhost:{A.port}/  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", A.port), Handler).serve_forever()
