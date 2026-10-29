#!/usr/bin/env python3
"""
**마디 라벨링 화면** — 로컬 전용(127.0.0.1). 엔진이 실패하는 마디의 정답을 모은다.

    .venv/bin/python tools/label_server.py data/label_queue   # → http://127.0.0.1:5290

eval/label_queue.py 가 만든 queue.jsonl 을 읽어 한 마디씩 보여 주고, 답을
labels.jsonl 에 한 줄씩 덧붙인다(같은 마디를 다시 답하면 마지막 답이 이긴다).
그림·라벨은 data/ 아래에만 남는다(git 제외).
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/label_queue").resolve()
PORT = int(os.environ.get("PORT", "5290"))
ORDER = {"불일치": 0, "짐작": 1, "자체수정": 2, "homr없음": 3}


def queue() -> list[dict]:
    items = [json.loads(l) for l in open(ROOT / "queue.jsonl") if '"key"' in l]
    return sorted(items, key=lambda it: (ORDER.get(it["why"], 9), it["key"]))


def labels() -> dict:
    out = {}
    p = ROOT / "labels.jsonl"
    if p.exists():
        for l in open(p):
            d = json.loads(l)
            out[d["key"]] = d
    return out


PAGE = r"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>마디 라벨링</title>
<style>
:root{--ink:#1d2330;--sub:#5d6575;--line:#d9dde5;--bg:#f6f7f9;--card:#fff;--acc:#2f5bd3;--ok:#1f8a4c;--warn:#b7791f}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 "Pretendard Variable",system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{display:flex;gap:16px;align-items:baseline;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--card)}
header h1{font-size:16px;margin:0}#prog{color:var(--sub);font-variant-numeric:tabular-nums}
main{max-width:960px;margin:0 auto;padding:16px 20px 60px;display:grid;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
#img{width:100%;border-radius:6px;border:1px solid var(--line);background:#fff}
.meta{color:var(--sub);font-size:13px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.opt{flex:1 1 280px;border:2px solid var(--line);border-radius:10px;padding:10px 12px;background:#fff;cursor:pointer;text-align:left;font:inherit}
.opt:hover,.opt:focus-visible{border-color:var(--acc);outline:none}
.opt b{display:block;font-size:12px;color:var(--sub);font-weight:600;margin-bottom:2px}
.seq{font:600 18px/1.4 ui-monospace,Menlo,monospace;letter-spacing:.5px}
.beats{font-size:12px;color:var(--sub)}.bad{color:#b42318}
.pad button{min-width:46px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;font:600 15px ui-monospace,Menlo,monospace;cursor:pointer}
.pad button:hover{border-color:var(--acc)}
#edit{font:600 18px ui-monospace,Menlo,monospace;width:100%;padding:8px 10px;border:2px solid var(--line);border-radius:8px}
.act{padding:9px 14px;border-radius:8px;border:1px solid var(--line);background:#fff;font:inherit;cursor:pointer}
.act.primary{background:var(--acc);border-color:var(--acc);color:#fff}
kbd{font:12px ui-monospace,Menlo,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 4px;background:#fff}
.help{color:var(--sub);font-size:13px}
#done{display:none;text-align:center;padding:40px}
</style>
<header><h1>마디 라벨링</h1><span id="prog"></span><span class="help" style="margin-left:auto">
<kbd>1</kbd> 우리 <kbd>2</kbd> homr <kbd>Enter</kbd> 직접 입력 저장 <kbd>S</kbd> 건너뛰기 <kbd>U</kbd> 지원 안 함 <kbd>←</kbd> 이전</span></header>
<main>
<div class="card"><img id="img" alt="마디 그림"><div class="meta" id="meta"></div></div>
<div class="card"><div class="row">
<button class="opt" id="o1"><b>1 · 우리 판독</b><span class="seq" id="s1"></span> <span class="beats" id="b1"></span></button>
<button class="opt" id="o2"><b>2 · homr 판독</b><span class="seq" id="s2"></span> <span class="beats" id="b2"></span></button>
</div></div>
<div class="card">
<div class="help" style="margin-bottom:6px">둘 다 틀리면 직접 입력 — 음표 <b>1 2 4 8 16</b>, 쉼표는 앞에 <b>r</b>, 점은 뒤에 <b>.</b> (예: <code>8. 16 8 8 r4 4</code>). 붙임줄은 적지 않아도 됩니다.</div>
<input id="edit" autocomplete="off" spellcheck="false" placeholder="8. 16 8 8 4 4">
<div class="row" style="margin-top:8px"><div class="pad row" id="pad"></div>
<span class="beats" id="be"></span><span style="flex:1"></span>
<button class="act" id="skip">건너뛰기 (S)</button><button class="act" id="unsup">지원 안 함 (U)</button>
<button class="act primary" id="save">입력값 저장 (Enter)</button></div>
</div>
<div class="card" id="done"><h2>다 했습니다 🎉</h2><p class="help">라벨은 data/label_queue/labels.jsonl 에 저장됐습니다.</p></div>
</main>
<script>
const $=id=>document.getElementById(id);let cur=null,hist=[];
const BE={'1':4,'2':2,'4':1,'8':.5,'16':.25,'32':.125};
function beats(seq){let t=0;for(const x of seq){const m=/^r?(\d+)(\.?)$/.exec(x);if(!m||!(m[1] in BE))return NaN;t+=BE[m[1]]*(m[2]?1.5:1)}return t}
function paintBeats(el,seq){const b=beats(seq);el.textContent=isNaN(b)?'형식 오류':`${b}박`;el.classList.toggle('bad',isNaN(b)||b!==4)}
async function load(key){const r=await fetch('/api/next'+(key?`?key=${encodeURIComponent(key)}`:''));const d=await r.json();
 $('prog').textContent=`${d.done} / ${d.total} 완료`;if(!d.item){$('done').style.display='block';return}
 cur=d.item;$('img').src=`/img/${cur.key}.png`;$('meta').textContent=`${cur.page} · ${cur.system+1}단 ${cur.measure}마디 · ${cur.why}`;
 $('s1').textContent=cur.ours.join(' ');paintBeats($('b1'),cur.ours);
 $('s2').textContent=cur.homr.length?cur.homr.join(' '):'(짝 없음)';if(cur.homr.length)paintBeats($('b2'),cur.homr);else $('b2').textContent='';
 $('o2').disabled=!cur.homr.length;$('edit').value=(cur.prev||cur.ours).join(' ');paintBeats($('be'),$('edit').value.trim().split(/\s+/))}
async function send(kind,answer){let ok=false;try{const r=await fetch('/api/label',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({key:cur.key,kind,answer})});ok=r.ok}catch(e){}
 if(!ok){alert('저장하지 못했습니다 — 라벨링 서버가 꺼졌을 수 있습니다. 알려 주세요.');return}
 hist.push(cur.key);load()}
$('o1').onclick=()=>send('ours',cur.ours);$('o2').onclick=()=>cur.homr.length&&send('homr',cur.homr);
$('save').onclick=()=>{const s=$('edit').value.trim().split(/\s+/).filter(Boolean);if(isNaN(beats(s)))return alert('형식을 확인해 주세요');send('custom',s)};
$('skip').onclick=()=>send('skip',null);$('unsup').onclick=()=>send('unsupported',null);
$('edit').addEventListener('input',()=>paintBeats($('be'),$('edit').value.trim().split(/\s+/)));
for(const t of ['1','2','4','8','16','.','r','⌫']){const b=document.createElement('button');b.textContent=t;b.onclick=()=>{const e=$('edit');
 if(t==='⌫'){e.value=e.value.trim().split(/\s+/).slice(0,-1).join(' ')}else if(t==='.'){e.value=e.value.replace(/\s*$/,'.')}
 else if(t==='r'){e.value=(e.value.trim()+' r').trim()}else{e.value=(e.value.trim().endsWith('r')?e.value.trim()+t:(e.value.trim()+' '+t).trim())}
 e.dispatchEvent(new Event('input'));e.focus()};$('pad').appendChild(b)}
document.addEventListener('keydown',e=>{if(!cur)return;const typing=document.activeElement===$('edit');
 if(e.key==='Enter'){e.preventDefault();$('save').click();return}
 if(typing)return;
 if(e.key==='1')$('o1').click();else if(e.key==='2')$('o2').click();else if(e.key==='s'||e.key==='S')$('skip').click();
 else if(e.key==='u'||e.key==='U')$('unsup').click();else if(e.key==='ArrowLeft'&&hist.length)load(hist.pop())});
load();
</script></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if path.startswith("/img/"):
            name = os.path.basename(path)
            f = ROOT / "img" / name
            if not name.endswith(".png") or not f.is_file():
                return self._send(404, b"", "text/plain")
            return self._send(200, f.read_bytes(), "image/png")
        if path == "/api/next":
            items, lab = queue(), labels()
            want = None
            if qs.startswith("key="):
                import urllib.parse
                want = urllib.parse.unquote(qs[4:])
            item = next((it for it in items if it["key"] == want), None) if want else \
                next((it for it in items if it["key"] not in lab), None)
            if item and item["key"] in lab and lab[item["key"]].get("answer"):
                item = {**item, "prev": lab[item["key"]]["answer"]}
            body = json.dumps({"item": item, "done": len(lab), "total": len(items)},
                              ensure_ascii=False).encode()
            return self._send(200, body, "application/json")
        self._send(404, b"", "text/plain")

    def do_POST(self):
        if self.path != "/api/label":
            return self._send(404, b"", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(min(n, 8192)) or b"{}")
        rec = {"key": str(d.get("key")), "kind": str(d.get("kind")),
               "answer": d.get("answer"), "at": int(time.time())}
        with open(ROOT / "labels.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._send(200, b"{}", "application/json")


if __name__ == "__main__":
    print(f"http://127.0.0.1:{PORT}  ({ROOT})")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
