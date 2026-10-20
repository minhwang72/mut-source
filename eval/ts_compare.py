"""
LLM 박자표 vs 마디 합 추정 — **어디서 갈리는가.**

깨진 마디 수로는 못 가른다: 박자를 틀리게 잡아도 그에 맞춰 자기 일관되면
오히려 잘 맞는 것처럼 보인다. 그래서 두 값이 **다른 장만** 뽑아 사람이 본다.
"""
import sys, os, glob, json, warnings
sys.path.insert(0, "tools"); warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
from ultralytics import YOLO

cache = json.load(open("eval/llm_counts_cache.json"))
M = YOLO("models/omr.pt")
same = diff = noTS = 0
rows_out = []
for p in sorted(glob.glob("악보샘플/이미지/*.png")):
    n = os.path.basename(p)[:-4]
    try:
        big, _ = P.upscale(Image.open(p).convert("RGB"))
        ink, st = cv.find_staves_best(big.convert("L"))
        if not st:
            continue
        sp = cv.median_spacing(st)
        rows = (cache.get(n, {}).get("systems") if isinstance(cache.get(n), dict)
                else cache.get(n)) or []
        ts = next((str(r.get("time_signature")) for r in rows
                   if r.get("time_signature")), "")
        base = [{"notes": int((rows[i] if i < len(rows) else {}).get("notes") or 0),
                 "rests": int((rows[i] if i < len(rows) else {}).get("rests") or 0),
                 "marks": []} for i in range(len(st))]
        ex, exr = DS.expects(base)
        boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
        strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
        gray = np.asarray(big.convert("L")).astype("float32")
        # A: 박자표 없이 (마디 합 추정)
        dA = DS.build_from(boxes, st, strict, sp, gray, base, meta=meta)
        # B: 박자표 주고
        withts = [dict(c, time_signature=ts) for c in base]
        dB = DS.build_from(boxes, st, strict, sp, gray, withts, meta=meta)
    except Exception as e:
        print(f"{n}: 건너뜀 ({str(e)[:40]})", flush=True); continue
    bA, bB = dA.get("beats"), dB.get("beats")
    badA = (lambda c: len(c.get("over") or []) + len(c.get("under") or []))(CB.check(dA, int(bA or 4)))
    badB = (lambda c: len(c.get("over") or []) + len(c.get("under") or []))(CB.check(dB, int(bB or 4)))
    if not ts: noTS += 1
    elif abs((bA or 0) - (bB or 0)) < 1e-6: same += 1
    else:
        diff += 1
        rows_out.append((n, ts, bA, bB, badA, badB))
    print(f"{n}: ts='{ts}' 추정 {bA} vs 박자표 {bB} · 깨짐 {badA} vs {badB}", flush=True)

print(f"\n=== 박자표 있는 장 중 일치 {same} · 불일치 {diff} · 박자표 없음 {noTS}")
print("불일치 장:")
for n, ts, bA, bB, badA, badB in rows_out:
    print(f"  {n:14s} 박자표 '{ts}'({bB}박) vs 추정 {bA}박 · 깨짐 추정{badA} 박자표{badB}")
