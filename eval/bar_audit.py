"""
마디 규칙 위반을 **전수로 분류한다.**

판정은 `checkbeats.check` 를 그대로 쓴다. 따로 세면 **단 경계에서 쪼개진
마디**(앞 단 2박 + 뒷 단 2박 = 한 마디)가 전부 "모자람"으로 잡힌다 —
처음에 그렇게 세서 short 가 62%로 나왔고, 첫·마지막 마디에 쏠린 게
그 증거였다.

"종종 안 맞는다"로는 못 고친다. 어긋난 마디가 어떤 모양인지 갈라야
한 방에 잡을 수 있는지 알 수 있다:
  · merge  : 합이 정확히 2배 — 마디선을 놓쳐 두 마디가 붙었다
  · split  : 합이 절반 — 없는 마디선을 넣어 한 마디를 쪼갰다
  · short  : 그 밖에 모자람 (음표·쉼표를 덜 읽음)
  · over   : 그 밖에 넘침
이웃과 짝을 이루는지(한쪽 2배 + 옆 모자람)도 함께 센다 — 짝이면 경계 문제다.
"""
import sys, os, glob, json, warnings
sys.path.insert(0, "tools"); warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
from ultralytics import YOLO

CACHE = "eval/llm_counts_cache.json"
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
M = YOLO("models/omr.pt")
V = {"whole":4.,"half":2.,"quarter":1.,"eighth":.5,"16th":.25,"32nd":.125}
kinds = {"merge":0,"split":0,"short":0,"over":0}
paired = 0; total_bad = 0; total_bars = 0; pages = 0
detail = []

for p in sorted(glob.glob("악보샘플/이미지/*.png")):
    name = os.path.basename(p)[:-4]
    try:
        big, _ = P.upscale(Image.open(p).convert("RGB"))
        ink, st = cv.find_staves_best(big.convert("L"))
        sp = cv.median_spacing(st)
        rows = (cache.get(name, {}).get("systems") if isinstance(cache.get(name), dict)
                else cache.get(name)) or []
        counts = [{"notes": int((rows[i] if i < len(rows) else {}).get("notes") or 0),
                   "rests": int((rows[i] if i < len(rows) else {}).get("rests") or 0),
                   "marks": []} for i in range(len(st))]
        ex, exr = DS.expects(counts)
        boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
        strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
        gray = np.asarray(big.convert("L")).astype("float32")
        d = DS.build_from(boxes, st, strict, sp, gray, counts, meta=meta)
    except Exception as e:
        print(f"{name}: 건너뜀 ({str(e)[:50]})", flush=True); continue
    pages += 1
    full = float(d.get("beats") or 4)
    ck = CB.check(d, int(full))
    total_bars += ck.get("ok", 0) + len(ck.get("over") or []) + len(ck.get("under") or [])
    bad = [(si, m, v, "over") for si, m, v in (ck.get("over") or [])]
    bad += [(si, m, v, "under") for si, m, v in (ck.get("under") or [])]
    total_bad += len(bad)
    bysys = {}
    for si, m, v, _ in bad:
        bysys.setdefault(si, set()).add(m)
    for si, m, v, side in bad:
        if abs(v - full*2) < 1e-6: kind = "merge"
        elif abs(v - full/2) < 1e-6: kind = "split"
        else: kind = "over" if side == "over" else "short"
        kinds[kind] += 1
        if side == "over" and ((m-1) in bysys[si] or (m+1) in bysys[si]):
            paired += 1
        if len(detail) < 25:
            detail.append((name, si+1, m+1, round(v,2), kind))
    print(f"{name}: 누적 어긋난 마디 {total_bad}/{total_bars}", flush=True)

print("\n=== 마디 규칙 위반 분류")
print(f"  전체 마디 {total_bars} · 어긋남 {total_bad} ({total_bad/max(1,total_bars)*100:.1f}%) · {pages}장")
for k, v in kinds.items():
    print(f"    {k:6s} {v:4d} ({v/max(1,total_bad)*100:.0f}%)")
print(f"  넘침이 옆 모자람과 짝을 이루는 경우 {paired} — 경계(마디선) 문제")
print("\n=== 사례")
for n, si, m, v, kind in detail[:14]:
    print(f"  {n:16s} 단{si} 마디{m}: {v}박 ({kind})")
