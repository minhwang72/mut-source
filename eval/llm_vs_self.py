"""**LLM 개수 단서가 아직 값을 하는가.**

같은 80장 · 같은 모델 · 같은 코드로 두 번 돌린다. 다른 건 `expect` 출처뿐:
  · self : 검출기 자체 개수 (LLM 0회, 원가 0원)
  · llm  : readcounts 가 읽은 단별 음표·쉼표 수 (장당 $0.094)

정답 악보가 없으므로 박자 검산(마디 합)으로 잰다. LLM 응답은 캐시한다 —
다시 돌릴 때 돈이 또 나가면 실험을 반복할 수 없다.
"""
import sys, os, json, glob, time, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
import readcounts as RC
from ultralytics import YOLO

MODEL = os.environ.get("MUTE_MODEL", "runs/detect/runs/omr_marks/weights/best.pt")
CACHE = "eval/llm_counts_cache.json"
RESULTS = "eval/llm_vs_self_results.json"   # 장별 결과 — 죽어도 이어서 돈다
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
done = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {}
M = YOLO(MODEL)
PAGES = [(os.path.basename(p)[:-4], p) for p in sorted(glob.glob("악보샘플/이미지/*.png"))]


def prep(path):
    big, _ = P.upscale(Image.open(path).convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
    gray = np.asarray(big.convert("L")).astype("float32")
    return big, ink, st, sp, strict, gray


def self_counts(big, st):
    bx, _ = E.detect_by_staff(M, big, 0.50)
    mids = [(s.top + s.bottom) / 2 for s in st]
    n = [0]*len(st); r_ = [0]*len(st)
    for b in bx:
        i = min(range(len(mids)), key=lambda k: abs(mids[k]-(b["y"]+b["h"]/2)))
        if b["class"].startswith("notehead"): n[i] += 1
        elif b["class"].startswith("rest"): r_[i] += 1
    return [{"notes": n[i], "rests": r_[i], "marks": []} for i in range(len(st))]


def llm_counts(name, path, nst):
    if name in cache:
        c = cache[name]
    else:
        c = RC.read_page(Image.open(path).convert("RGB"))
        cache[name] = c
        json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
    rows = (c.get("systems") if isinstance(c, dict) else c) or []
    out = []
    for i in range(nst):
        r = rows[i] if i < len(rows) else {}
        out.append({"notes": int(r.get("notes") or 0),
                    "rests": int(r.get("rests") or 0), "marks": []})
    return out


def score(counts, big, st, sp, strict, gray):
    ex, exr = DS.expects(counts)
    boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
    tm = "models/omr_tie.pt"
    curves = DS.detect_curves(big, tm, ex, exr) if os.path.exists(tm) else None
    d = DS.build_from(boxes, st, strict, sp, gray, counts, curves=curves, meta=meta)
    ck = CB.check(d, int(d.get("beats") or 4))
    heads = sum(1 for b in boxes if b["class"].startswith("notehead"))
    ch = sum(1 for s in d.get("systems", []) for n in s.get("notes", []) if n.get("chord"))
    return ck.get("ok", 0), len(ck.get("over") or []) + len(ck.get("under") or []), heads, ch


tot = {"self": [0,0,0,0], "llm": [0,0,0,0]}
win = {"self": 0, "llm": 0, "tie": 0}
t0 = time.time()
for i, (name, path) in enumerate(PAGES, 1):
    try:
        if name in done:
            a, b = done[name]["self"], done[name]["llm"]
        else:
            big, ink, st, sp, strict, gray = prep(path)
            a = score(self_counts(big, st), big, st, sp, strict, gray)
            b = score(llm_counts(name, path, len(st)), big, st, sp, strict, gray)
            done[name] = {"self": list(a), "llm": list(b)}
            json.dump(done, open(RESULTS, "w"))
    except Exception as e:
        print(f"{i:3d}/{len(PAGES)} {name}: 건너뜀 ({str(e)[:60]})", flush=True)
        continue
    for k, v in (("self", a), ("llm", b)):
        for j in range(4): tot[k][j] += v[j]
    if   a[1] < b[1]: win["self"] += 1
    elif b[1] < a[1]: win["llm"] += 1
    else: win["tie"] += 1
    print(f"{i:3d}/{len(PAGES)} {name:16s} self 맞음{a[0]:3d}/틀림{a[1]:3d} 머리{a[2]:4d} 화음{a[3]:3d}"
          f" │ llm 맞음{b[0]:3d}/틀림{b[1]:3d} 머리{b[2]:4d} 화음{b[3]:3d}"
          f"  ({(time.time()-t0)/60:.0f}분)", flush=True)

print("\n=== 80장 합계")
for k in ("self", "llm"):
    o, bad, h, c = tot[k]
    lab = "self(LLM 0회)" if k == "self" else "llm(장당 $0.094)"
    print(f"  {lab:18s} 맞음 {o:5d} · 불일치 {bad:4d} · 머리 {h:6d} · 화음 {c:4d}")
print(f"  장 단위 승패 — self {win['self']} · llm {win['llm']} · 같음 {win['tie']}")
