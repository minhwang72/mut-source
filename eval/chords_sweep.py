"""코드만 바꾸기 경로 측정: 장마다 상태·의심 코드 수·시간. eval/sweep.py 의 코드만 판."""
import sys, os, json, time
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
import devcache
devcache.install()
import serve
serve.STATE["mode"] = "ai"
DIR = os.environ.get("SWEEP_DIR") or "악보샘플/학습용_이미지"
OUT = os.environ.get("SWEEP_OUT") or "eval/chords_sweep.json"
SDIR = OUT[:-5] + "_structs"
os.makedirs(SDIR, exist_ok=True)
rows = []
for name in sys.argv[1:]:
    t = time.time()
    try:
        ex = serve.read_sheet(open(f"{DIR}/{name}.png", "rb").read(), None, "chords")
        json.dump(ex, open(f"{SDIR}/{name}.json", "w"), ensure_ascii=False)
        g = ex["qualityGate"]
        n = sum(len(s.get("chords") or []) for s in ex["systems"])
        r = {"page": name, "status": g["status"], "chords": n, "doubt": len(g["flagged"]),
             "key": ex["meta"]["key"], "secs": round(time.time() - t, 1)}
    except Exception as e:                       # noqa: BLE001
        r = {"page": name, "status": "error", "err": f"{type(e).__name__}: {e}"[:150],
             "secs": round(time.time() - t, 1)}
    rows.append(r)
    print(json.dumps(r, ensure_ascii=False), flush=True)
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
ok = [r for r in rows if r["status"] != "error"]
print(f"== {len(rows)}장 · ready {sum(r['status']=='ready' for r in rows)} · marked "
      f"{sum(r['status']=='marked' for r in rows)} · 오류 {len(rows)-len(ok)} · 코드 "
      f"{sum(r['chords'] for r in ok)} 중 의심 {sum(r['doubt'] for r in ok)}")
