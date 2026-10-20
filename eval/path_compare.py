"""
**local 과 ai, 어느 쪽이 실제인가.**

배포된 서버는 ai 모드다 — 단별 음표·쉼표 개수를 LLM 에 묻고 그 개수로
검출을 유도한다. 그런데 105장 측정은 local 모드(외부 호출 없음)로 했고
거기서 통과 0% 가 나왔다. 개수 유도가 빠지면 검출이 나빠지므로 그 0% 는
실제보다 비관적일 수 있다 — 얼마나인지 재야 한다.

개수는 eval/counts 에 8장치가 캐시돼 있다. **캐시만 쓴다** — 없으면
건너뛴다. 새로 묻지 않으니 돈이 들지 않는다.
"""
import sys, os, json, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
import local_reader as LR
import detstruct as DS
import db as DB

CACHE = "eval/counts"
names = sorted(f[:-5] for f in os.listdir(CACHE) if f.endswith(".json"))


def issues_for(path, counts):
    """counts 가 None 이면 local(무유도), 있으면 ai 와 같은 유도 경로."""
    orig = DS.expects
    if counts is not None:
        # ai 경로는 LLM 개수를 detect 에 준다. local_reader 는 자체 개수를
        # 쓰므로, 같은 자리에 캐시된 개수를 꽂아 **그 차이만** 만든다.
        ex, exr = orig(counts)
        LR._local_expects = lambda boxes, staves: (ex, exr)
    else:
        import importlib
        importlib.reload(LR)
    ex_ = LR.read_sheet_local(open(path, "rb").read())
    g = ex_["qualityGate"]
    return g, [DB.issue_kind(m) for m in g.get("blocking", g["issues"])]


rows = []
for n in names:
    p = f"악보샘플/이미지/{n}.png"
    if not os.path.exists(p):
        continue
    counts = json.load(open(f"{CACHE}/{n}.json"))["systems"]
    out = {"page": n}
    for label, c in (("local", None), ("ai", counts)):
        try:
            g, ks = issues_for(p, c)
            out[label] = {"status": g["status"], "n": len(ks), "kinds": ks}
        except Exception as e:                   # noqa: BLE001
            out[label] = {"status": "오류", "n": -1, "kinds": [],
                          "err": f"{type(e).__name__}: {e}"[:80]}
    rows.append(out)
    print(f"{n:16}  local {out['local']['n']:3}  →  ai {out['ai']['n']:3}"
          f"   {out['local']['status']:13} → {out['ai']['status']}", flush=True)

ok = lambda k: sum(1 for r in rows if r[k]["n"] == 0)                # noqa: E731
tot = lambda k: sum(max(0, r[k]["n"]) for r in rows)                 # noqa: E731
print(f"\n== {len(rows)}장 (차단 사유만 셈)")
print(f"  local  통과 {ok('local')}장 · 차단 사유 {tot('local')}건")
print(f"  ai     통과 {ok('ai')}장 · 차단 사유 {tot('ai')}건")
for k in ("local", "ai"):
    c = collections.Counter(x for r in rows for x in r[k]["kinds"])
    print(f"\n  [{k}] 사유별")
    for kind, v in c.most_common(6):
        print(f"    {v:4}  {kind}")
json.dump(rows, open("eval/path_compare.json", "w"), ensure_ascii=False, indent=1)
