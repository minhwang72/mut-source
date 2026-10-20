"""
**통째로 빠진 음표·쉼표 — 검출이 아예 못 봤나, 보고도 버렸나.**

어긋난 마디 중 모자람이 표준 음가(0.25·0.5·1·2·4박)와 정확히 같은 것은
"뭔가 하나가 통째로 빠졌다"는 뜻이다. 고칠 자리는 둘로 갈린다.

  ① 버린 후보(spare)가 그 마디에 있다  → 되살리기(promote_heads)가 왜 안
     받았나. 문턱·규칙 문제라 코드로 고친다.
  ② 후보조차 없다                      → 검출이 그 자리에서 아무것도 못
     봤다. 문턱으로 못 고친다 — 학습이나 다른 축이 필요하다.

둘의 비율을 모르면 어디에 힘을 쓸지 정할 수 없다.
"""
import sys, collections
sys.path.insert(0, "eval")
exec(open("eval/dur_why.py").read().split("_c = install()")[0])
_c = install()
import serve                                                   # noqa: E402
import checkbeats as CB                                        # noqa: E402

serve.STATE["mode"] = "ai"
STD = {0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0}
kind = collections.Counter()
conf_hist = collections.Counter()
fit = collections.Counter()
dur_hist = collections.Counter()
_BEAT = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}
rows = []

# detect_guided 의 spare 를 받아 두려면 _read_structure 를 거치지 않고
# 직접 불러야 한다 — serve.read_sheet 는 meta 를 안 돌려준다.
import numpy as np                                             # noqa: E402
import sheetcv as cv                                           # noqa: E402
import evaldet as E                                            # noqa: E402
import detstruct as DS                                         # noqa: E402
import probe as P                                              # noqa: E402
from PIL import Image                                          # noqa: E402
from ultralytics import YOLO                                   # noqa: E402

M = YOLO("models/omr.pt")
for name in sys.argv[1:]:
    _c.page = name
    try:
        ex = serve.read_sheet(open(f"악보샘플/이미지/{name}.png", "rb").read(), None)
    except Exception as e:                                     # noqa: BLE001
        print(f"{name:16} 오류 {str(e)[:40]}", flush=True)
        continue
    st_ = ex.get("struct") or {}
    geo = ex.get("geometry") or {}
    if not st_.get("systems"):
        continue
    big, _s = P.upscale(Image.open(f"악보샘플/이미지/{name}.png").convert("RGB"))
    ink, staves = cv.find_staves_best(big)
    sp = cv.median_spacing(staves)
    exn, exr = DS.expects(_c.page and __import__("json").load(
        open("eval/llm_counts_cache.json"))[name]["systems"])
    _b, meta = E.detect_guided(M, big, exn, expect_rests=exr)
    gray_ = np.asarray(big.convert("L")).astype("float32")
    spare = meta.get("spare") or []

    beats = int(st_.get("beats") or 4)
    per = CB.beats_per_measure(st_)
    skip = {(i, m) for i, m, _ in CB.splits(per, beats * 8)}
    skip |= {(i + 1, f) for i, _, f in CB.splits(per, beats * 8)}
    for i, pm in enumerate(per):
        bars = (geo["systems"][i].get("bars")
                if i < len(geo.get("systems") or []) else None)
        for m, v in pm.items():
            if (i, m) in skip or v == beats * 8:
                continue
            d = (v - beats * 8) / 8.0
            d_ = d
            if d >= 0 or abs(d) not in STD:
                continue
            # 이 마디의 x 구간 — 막대선이 있으면 그걸 쓴다
            lo, hi = None, None
            if bars and len(bars) >= 2:
                edges = [staves[i].left] + list(bars) + [staves[i].right]
                if m - 1 < len(edges) - 1:
                    lo, hi = edges[m - 1], edges[m]
            if lo is None:
                kind["마디 구간을 못 잡음"] += 1
                continue
            cands = [c for c in (spare[i] if i < len(spare) else [])
                     if lo <= c["x"] + c["w"] / 2.0 < hi]
            if cands:
                kind["버린 후보가 있다"] += 1
                conf_hist[round(max(c["conf"] for c in cands), 1)] += 1
                # **후보를 넣으면 정말 맞는가.**
                # 후보만 떼서 음가를 매기면 안 된다 — 빔·꼬리 상자가 같이
                # 안 가서 전부 기본값(4분·2분·온)으로 읽힌다. promote_heads
                # 는 그 단의 상자 전체에 후보를 더해서 읽으므로, 여기서도
                # 같게 해야 한다(측정 도구가 실제 경로와 달라지는 함정).
                import durations as _D
                mid_ = (staves[i].top + staves[i].bottom) / 2.0
                half_ = (staves[i].bottom - staves[i].top) * 1.4
                grp_ = [b for b in _b
                        if abs(b["y"] + b["h"] / 2.0 - mid_) < half_]
                got = _D.read_durations(grp_ + cands, sp, gray=gray_)
                keys = {(round(c["x"], 1), round(c["y"], 1)) for c in cands}
                vals = sorted({(g["duration"], bool(g.get("dotted")))
                               for g in got
                               if (round(g["x"], 1), round(g["y"], 1)) in keys})
                hit = any(_BEAT[u] * (1.5 if dt else 1.0) == -d_ for u, dt in vals)
                fit["맞는 후보 있음" if hit else "넣어도 안 맞음"] += 1
                for u, dt in vals:
                    dur_hist[f"{u}{'.' if dt else ''} vs {-d_:.2f}박"] += 1
            else:
                kind["후보조차 없다"] += 1
            rows.append((name, i, m, d, len(cands)))

n = max(1, sum(kind.values()))
print(f"\n== 통째로 빠진 것으로 보이는 마디 {n}개\n")
for k, c in kind.most_common():
    print(f"  {c:4} ({c/n:4.0%})  {k}")
print("\n버린 후보가 있을 때 그 최고 점수")
for k in sorted(conf_hist):
    print(f"  {k:.1f}  {conf_hist[k]:4}")
print("\n버린 후보를 넣으면 맞는가")
for k, c in fit.most_common():
    print(f"  {c:4}  {k}")
print("\n후보 음가 vs 모자람 (상위 12)")
for k, c in dur_hist.most_common(12):
    print(f"  {c:4}  {k}")
print("\n모자람 크기별")
sz = collections.Counter(r[3] for r in rows)
for k, c in sorted(sz.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  {k:+5.2f}박  {c:4}")
