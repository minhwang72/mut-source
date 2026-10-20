"""
**통과해서 과금되는 장만 보면 얼마나 깨져 있나.**

전체 깨진 마디 비율은 팔 수 있느냐를 말해 주지 않는다 — 게이트가 막는
장(× 머리·2성부 등)이 섞여 있기 때문이다. 돈을 받는 장만 따로 세야
"지금 팔아도 되나"에 답할 수 있다.
"""
import sys, collections
sys.path.insert(0, "eval")
exec(open("eval/dur_why.py").read().split("_c = install()")[0])
_c = install()
import serve                                                   # noqa: E402
import local_reader as LR                                      # noqa: E402
import checkbeats as CB                                        # noqa: E402

serve.STATE["mode"] = "ai"
tot = collections.Counter()
rows = []
for name in sys.argv[1:]:
    _c.page = name
    try:
        ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
    except Exception as e:                                     # noqa: BLE001
        print(f"{name:16} 오류 {str(e)[:40]}", flush=True)
        continue
    st = ex.get("struct") or {}
    if not st.get("systems"):
        continue
    g = LR.quality_gate(ex, [])
    beats = int(st.get("beats") or 4)
    per = CB.beats_per_measure(st)
    skip = {(i, m) for i, m, _ in CB.splits(per, beats * 8)}
    skip |= {(i + 1, f) for i, _, f in CB.splits(per, beats * 8)}
    n = bad = 0
    for i, pm in enumerate(per):
        for m, v in pm.items():
            if (i, m) in skip:
                continue
            n += 1
            if v != beats * 8:
                bad += 1
    gs = sum(1 for s in st["systems"] for x in s["notes"] if x.get("guessed"))
    ok = g["status"] == "ready"
    tot["장"] += 1
    tot["통과 장" if ok else "차단 장"] += 1
    if ok:
        tot["통과 마디"] += n
        tot["통과 깨진 마디"] += bad
        tot["통과 지어낸 음가"] += gs
    rows.append((name, g["status"], n, bad, gs))
    print(f"{name:16} {g['status']:13} 마디 {n:3} · 깨짐 {bad:3} · 지어냄 {gs:3}",
          flush=True)

print("\n== " + " · ".join(f"{k} {v}" for k, v in tot.items()))
if tot["통과 마디"]:
    print(f"통과한 장의 깨진 마디 비율 "
          f"{tot['통과 깨진 마디'] / tot['통과 마디']:.1%}")
