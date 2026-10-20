"""
**어긋난 마디를 증거와 함께 가른다 — short_why 의 확장판.**

short_why 는 "붙임점 하나" 와 "한 단계 올리기" 만 봤다. 그 둘로 설명되지
않는 마디가 절반이었는데, 거기서 멈추면 1위 원인을 못 정한다. 여기서는
모자람/넘침을 따로 보고, 설명 못 하는 것도 **왜 못 하는지**를 가른다.

  넘침  점 거두기 · 한 단계 내리기 · 음표 하나가 더 들어왔다
  모자람 점 붙이기 · 한 단계 올리기 · 음표/쉼표 하나가 통째로 빠졌다

"통째로 빠졌다"는 모자람이 표준 음가(0.25·0.5·1·2·4박)와 정확히 같을
때다 — 검출이 놓친 것이고, `promote_heads` 가 되살릴 후보조차 없었다는
뜻이라 고칠 자리가 다르다.
"""
import sys, collections
sys.path.insert(0, "eval")
exec(open("eval/dur_why.py").read().split("_c = install()")[0])
_c = install()
import serve                                                   # noqa: E402
import checkbeats as CB                                        # noqa: E402

serve.STATE["mode"] = "ai"
DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
UP = {"16th": "eighth", "eighth": "quarter", "quarter": "half",
      "half": "whole"}
DOWN = {v: k for k, v in UP.items()}
STD = {0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0}

why = collections.Counter()
ev = collections.defaultdict(list)
rows = []
for name in sys.argv[1:]:
    _c.page = name
    try:
        ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
    except Exception as e:                                     # noqa: BLE001
        print(f"{name:16} 오류 {str(e)[:50]}", flush=True)
        continue
    st = ex.get("struct") or {}
    if not st.get("systems"):
        continue
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
            tag = None
            for n in ns:
                base = DUR.get(n["duration"], 0)
                dot = bool(n.get("dotted"))
                cur = base * 3 // 2 if dot else base
                if d < 0:
                    if not dot and not n.get("rest") \
                            and (base // 2) / 8.0 == -d:
                        tag = "점 붙이기"
                        ev[tag].append(n.get("dotScore", 0.0))
                        break
                    up = UP.get(n["duration"])
                    if up:
                        nv = DUR[up] * 3 // 2 if dot else DUR[up]
                        if (nv - cur) / 8.0 == -d:
                            tag = "한 단계 올리기"
                            ev[tag].append(n.get("hollow", 0.0))
                            break
                else:
                    if dot and (base // 2) / 8.0 == d:
                        tag = "점 거두기"
                        ev[tag].append(n.get("dotScore", 0.0))
                        break
                    dn = DOWN.get(n["duration"])
                    if dn:
                        nv = DUR[dn] * 3 // 2 if dot else DUR[dn]
                        if (cur - nv) / 8.0 == d:
                            tag = "한 단계 내리기"
                            ev[tag].append(n.get("hollow", 0.0))
                            break
            if tag is None:
                if abs(d) in STD:
                    tag = ("음표·쉼표가 통째로 빠짐" if d < 0
                           else "없는 음표가 들어옴")
                else:
                    tag = "설명 못 함 (두 군데 이상)"
            why[tag] += 1
            rows.append((name, i, m, d, tag, len(ns)))

n = max(1, len(rows))
print(f"\n== 어긋난 마디 {len(rows)}개\n")
for k, c in why.most_common():
    print(f"  {c:4} ({c/n:4.0%})  {k}")
print("\n증거 분포")
for k, vals in ev.items():
    h = collections.Counter(round(x, 1) for x in vals)
    print(f"  {k:12} {sorted(h.items())}")
print("\n어긋남 크기별")
sz = collections.Counter(r[3] for r in rows)
for k, c in sorted(sz.items(), key=lambda kv: -kv[1])[:10]:
    print(f"  {k:+6.2f}박  {c:4}")
