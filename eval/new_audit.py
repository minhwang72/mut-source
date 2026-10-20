"""
**새 25장만** 실패 양상을 분류한다.

105장 전체 기준(short 58% · over 27%)이 새 악보에도 그대로인지 모른다.
튜닝해 온 80장과 섞어 보면 새 악보의 얼굴이 가려진다.
"""
import sys, os, glob, json, warnings
sys.path.insert(0, "tools"); warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
from ultralytics import YOLO

cache = json.load(open("eval/llm_counts_cache.json"))
M = YOLO("models/omr.pt")
NEW = ("now0918", "wish0920")
groups = {"새 25장": [], "기존 80장": []}
detail = []

for p in sorted(glob.glob("악보샘플/이미지/*.png")):
    n = os.path.basename(p)[:-4]
    key = "새 25장" if n.startswith(NEW) else "기존 80장"
    try:
        big, _ = P.upscale(Image.open(p).convert("RGB"))
        ink, st = cv.find_staves_best(big.convert("L"))
        if not st:
            continue
        sp = cv.median_spacing(st)
        rows = (cache.get(n, {}).get("systems") if isinstance(cache.get(n), dict)
                else cache.get(n)) or []
        counts = [{"notes": int((rows[i] if i < len(rows) else {}).get("notes") or 0),
                   "rests": int((rows[i] if i < len(rows) else {}).get("rests") or 0),
                   "marks": []} for i in range(len(st))]
        ex, exr = DS.expects(counts)
        boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
        strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
        gray = np.asarray(big.convert("L")).astype("float32")
        d = DS.build_from(boxes, st, strict, sp, gray, counts, meta=meta)
    except Exception as e:
        print(f"{n}: 건너뜀 ({str(e)[:40]})", flush=True); continue
    full = float(d.get("beats") or 4)
    ck = CB.check(d, int(full))
    bad = [(si, m, v, "over") for si, m, v in (ck.get("over") or [])]
    bad += [(si, m, v, "under") for si, m, v in (ck.get("under") or [])]
    tot = ck.get("ok", 0) + len(bad)
    for si, m, v, side in bad:
        if abs(v - full * 2) < 1e-6: kind = "merge"
        elif abs(v - full / 2) < 1e-6: kind = "split"
        else: kind = "over" if side == "over" else "short"
        groups[key].append((kind, v / full))
        if key == "새 25장":
            detail.append((n, si + 1, m + 1, v, kind))
    groups[key + "_tot"] = groups.get(key + "_tot", 0) + tot
    print(f"{n}: {len(bad)}/{tot}", flush=True)

from collections import Counter
print()
for key in ("새 25장", "기존 80장"):
    g = groups[key]; tot = groups.get(key + "_tot", 0)
    c = Counter(k for k, _ in g)
    print(f"=== {key} · 마디 {tot} · 어긋남 {len(g)} ({len(g)/max(1,tot)*100:.1f}%)")
    for k, v in c.most_common():
        print(f"    {k:6s} {v:4d} ({v/max(1,len(g))*100:.0f}%)")
    # 얼마나 어긋나는가 (박 비율)
    short = [r for k, r in g if k == "short"]
    over = [r for k, r in g if k == "over"]
    if short: print(f"    short 비율 중앙값 {np.median(short):.2f} (1.0 이 정답)")
    if over: print(f"    over  비율 중앙값 {np.median(over):.2f}")
print("\n=== 새 25장 최악 마디")
for n, si, m, v, k in sorted(detail, key=lambda r: -abs(r[3]))[:12]:
    print(f"  {n:14s} 단{si} 마디{m}: {v}박 ({k})")
