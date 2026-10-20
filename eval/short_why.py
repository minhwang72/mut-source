"""
**모자란 마디를 무엇으로 메울 수 있나 — 증거와 함께.**

fit_page 를 끄고 잰 어긋남 24개(7장 208마디) 중 1위는 -0.5박이다.
"한 단계 차이"라는 말만으로는 고칠 자리를 못 정한다. 마디마다
  · 붙임점을 붙이면 맞는가 → 그 음표의 **화소 점수**가 얼마인가
  · 음가를 한 단계 옮기면 맞는가 → 어느 방향인가
  · 아무것도 설명 못 하는가
를 증거와 함께 센다. 점수가 0.40 위면 문턱 문제, 0 에 가까우면 화소로도
안 보이는 것이라 고칠 자리가 다르다.
"""
import sys, collections
sys.path.insert(0, "eval")
exec(open("eval/dur_why.py").read().split("_c = install()")[0])
_c = install()
import serve                                                   # noqa: E402
import checkbeats as CB                                        # noqa: E402

serve.STATE["mode"] = "ai"
DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
STEP = {"16th": "eighth", "eighth": "quarter", "quarter": "half",
        "half": "whole"}
why = collections.Counter()
score_hist = collections.Counter()
rows = []
for name in sys.argv[1:]:
    _c.page = name
    ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
    st = ex["struct"]
    beats = int(st.get("beats") or 4)
    per = CB.beats_per_measure(st)
    skip = {(i, m) for i, m, _ in CB.splits(per, beats * 8)}
    skip |= {(i + 1, f) for i, _, f in CB.splits(per, beats * 8)}
    by = collections.defaultdict(list)
    for s in st["systems"]:
        for n in s["notes"]:
            by[(s["system"], n["measure"])].append(n)
    for i, pm in enumerate(per):
        for m, v in pm.items():
            if (i, m) in skip or v == beats * 8:
                continue
            d = (v - beats * 8) / 8.0
            ns = [n for n in by[(i, m)] if not n.get("chord")]
            tags = []
            for n in ns:
                base = DUR.get(n["duration"], 0)
                cur = base * 3 // 2 if n.get("dotted") else base
                # 붙임점을 붙이면?
                if not n.get("dotted") and not n.get("rest") \
                        and (base // 2) / 8.0 == -d:
                    sc = n.get("dotScore", 0.0)
                    tags.append(f"점+({sc:.2f})")
                    score_hist[round(sc, 1)] += 1
                # 한 단계 올리면?
                up = STEP.get(n["duration"])
                if up:
                    nv = DUR[up] * 3 // 2 if n.get("dotted") else DUR[up]
                    if (nv - cur) / 8.0 == -d:
                        tags.append(f"{n['duration']}→{up}"
                                    f"(속{n.get('hollow', 0):.2f})")
            why[tags[0].split("(")[0] if tags else "설명 못 함"] += 1
            rows.append((name, i, m, d, " · ".join(tags[:3]) or "—"))

print(f"\n== 모자라거나 넘치는 마디 {len(rows)}개")
for r in rows:
    print(f"  {r[0]:14} 단{r[1]} 마디{r[2]:2} {r[3]:+5.2f}박  {r[4]}")
print("\n한 번의 편집으로 설명되는가")
for k, c in why.most_common():
    print(f"  {c:4}  {k}")
print("\n'점을 붙이면 맞는' 음표의 화소 점수")
for k in sorted(score_hist):
    print(f"  {k:.1f}  {score_hist[k]:4}")
