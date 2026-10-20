"""
**곡 첫 마디가 못갖춘마디인 경우가 얼마나 되나.**

못갖춘마디(pickup)는 정상 조판이다. 그런데 검산은 "합이 모자란 마디"로 세어
오류로 잡는다. 표준 관행은 **첫 마디 + 마지막 마디 = 한 마디**다 — 그 짝이
실제로 맞는지 함께 본다. 맞으면 안심하고 면제할 수 있다.
"""
import sys, os, glob, json, warnings
sys.path.insert(0, "tools"); warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
from ultralytics import YOLO

cache = json.load(open("eval/llm_counts_cache.json"))
M = YOLO("models/omr.pt")
first_short = pair_ok = pair_bad = total_under = 0
rows_out = []
for p in sorted(glob.glob("악보샘플/이미지/*.png")):
    n = os.path.basename(p)[:-4]
    try:
        big, _ = P.upscale(Image.open(p).convert("RGB"))
        ink, st = cv.find_staves_best(big.convert("L"))
        if not st: continue
        sp = cv.median_spacing(st)
        rs = (cache.get(n, {}).get("systems") if isinstance(cache.get(n), dict)
              else cache.get(n)) or []
        ts = next((str(r.get("time_signature")) for r in rs if r.get("time_signature")), "")
        counts = [{"notes": int((rs[i] if i < len(rs) else {}).get("notes") or 0),
                   "rests": int((rs[i] if i < len(rs) else {}).get("rests") or 0),
                   "marks": [], "time_signature": ts if i == 0 else ""}
                  for i in range(len(st))]
        ex, exr = DS.expects(counts)
        boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
        strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
        gray = np.asarray(big.convert("L")).astype("float32")
        d = DS.build_from(boxes, st, strict, sp, gray, counts, meta=meta)
    except Exception as e:
        print(f"{n}: 건너뜀 ({str(e)[:40]})", flush=True); continue
    beats = float(d.get("beats") or 4)
    ck = CB.check(d, int(beats))
    under = ck.get("under") or []
    total_under += len(under)
    # 마디 번호는 **1부터**다(checkbeats 가 dict 키를 그대로 낸다).
    per_all = CB.beats_per_measure(d)
    first_key = min(per_all[0]) if per_all and per_all[0] else 1
    hit = [u for u in under if u[0] == 0 and u[1] == first_key]
    if not hit:
        print(f"{n}: 첫마디 정상", flush=True); continue
    first_short += 1
    v0 = hit[0][2]
    per = CB.beats_per_measure(d)
    last = per[-1]
    lastv = last[max(last)] / 8.0 if last else 0.0
    ok = abs(v0 + lastv - beats) < 1e-6
    pair_ok += ok; pair_bad += (not ok)
    rows_out.append((n, v0, lastv, beats, ok))
    print(f"{n}: 첫마디 {v0}박 · 마지막 {lastv}박 · 짝 {'맞음' if ok else '안맞음'}", flush=True)

print(f"\n=== 첫 마디가 모자란 장 {first_short} · 전체 under {total_under}")
print(f"  첫+마지막 = 한 마디  맞음 {pair_ok} · 안맞음 {pair_bad}")
