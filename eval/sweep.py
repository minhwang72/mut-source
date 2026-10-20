"""
**105장 전체를 배포와 같은 경로(ai 모드)로 돌려 게이트 결과를 남긴다.**

실사용 39건이 전부 환불됐는데 사유 기록이 없다. 테스트 악보로 같은 길을
그대로 밟아 무엇이 막는지 센다. 손으로 조립한 하네스가 1위 사유를 두 번
가짜로 만든 적이 있어, 서버가 부르는 serve.read_sheet() 를 그대로 부른다.

LLM 응답은 eval/aicache 에 남는다 — 처음 한 번만 돈이 들고 이후는 공짜.
결과: eval/sweep.json (장별), eval/sweep_structs/<장>.json (재분석용)
SWEEP_OUT=eval/sweep_b.json 으로 바꾸면 비교본을 따로 남긴다.
"""
import sys, os, json, time, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
import devcache
devcache.install()
import serve
import db as DB

serve.STATE["mode"] = "ai"
PAGES = sys.argv[1:] or sorted(f[:-4] for f in os.listdir("악보샘플/이미지")
                               if f.endswith(".png"))
OUT = os.environ.get("SWEEP_OUT") or "eval/sweep.json"   # 비교용으로 바꿔 쓴다
SDIR = OUT[:-5] + "_structs"
done = {r["page"]: r for r in json.load(open(OUT))} if os.path.exists(OUT) else {}
os.makedirs(SDIR, exist_ok=True)

for name in PAGES:
    if name in done:                       # 이어 돌리기 — 끊겨도 처음부터 안 한다
        continue
    t = time.time()
    try:
        ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
        g = ex["qualityGate"]
        st = ex.get("struct") or {}
        json.dump({"struct": st, "gate": g, "cross": ex.get("crossCheck")},
                  open(f"{SDIR}/{name}.json", "w"),
                  ensure_ascii=False)
        blk = list(g.get("blocking") or [])
        r = {"page": name, "status": g["status"], "blocking": blk,
             "notes": [m for m in g["issues"] if m not in blk],
             "kinds": [DB.issue_kind(m) for m in blk],
             "systems": len(st.get("systems") or []),
             "guessed": sum(1 for s in st.get("systems") or [] for x in s.get("notes", [])
                            if x.get("guessed")),
             "secs": round(time.time() - t, 1)}
    except Exception as e:                 # noqa: BLE001
        r = {"page": name, "status": "error", "blocking": [f"{type(e).__name__}: {e}"[:200]],
             "notes": [], "kinds": ["오류"], "secs": round(time.time() - t, 1)}
    done[name] = r
    json.dump(list(done.values()), open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"{name:14} {r['status']:12} 차단 {len(r['blocking']):2} {r['secs']:6}s "
          f"{(r['blocking'] or [''])[0][:60]}", flush=True)

rows = list(done.values())
ok = sum(r["status"] == "ready" for r in rows)
print(f"\n== {len(rows)}장 · 통과 {ok} ({ok / max(1, len(rows)):.0%})")
k = collections.Counter(); pk = collections.Counter()
for r in rows:
    k.update(r["kinds"]); pk.update(set(r["kinds"]))
for kind, c in k.most_common(15):
    print(f"  {c:4}건 {pk[kind]:3}장  {kind}")
