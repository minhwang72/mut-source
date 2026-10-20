"""옛 모델 vs 새 모델(화음 학습) — 박자 검산과 화음 기둥으로 비교한다.

정답 악보가 없으므로 음가 정확도는 못 잰다. 대신 두 가지를 본다:
  · 마디 합이 박자와 맞는가 (정답 없이도 되는 절대 검산)
  · 같은 x 에 머리가 쌓여 보이는가 (화음 학습의 목표)
개수 안내는 LLM 없이 검출기 자체 개수를 쓴다 — 두 모델에 같은 방식이라
비교는 공정하다.
"""
import sys, os, json, warnings
sys.path.insert(0, "tools")
warnings.filterwarnings("ignore")
import numpy as np
from PIL import Image
import probe as P, sheetcv as cv, evaldet as E, detstruct as DS, checkbeats as CB
from ultralytics import YOLO

OLD = "models/omr.pt"
NEW = "runs/detect/runs/omr_marks/weights/best.pt"
import glob
SHEETS = [(os.path.basename(p)[:-4], p)
          for p in sorted(glob.glob("악보샘플/이미지/*.png"))]


def run(M, path):
    big, _ = P.upscale(Image.open(path).convert("RGB"))
    ink, st = cv.find_staves_best(big.convert("L"))
    sp = cv.median_spacing(st)
    bx, _ = E.detect_by_staff(M, big, 0.50)
    mids = [(s.top + s.bottom) / 2 for s in st]
    n = [0] * len(st); r_ = [0] * len(st)
    for b in bx:
        i = min(range(len(mids)), key=lambda k: abs(mids[k] - (b["y"] + b["h"] / 2)))
        if b["class"].startswith("notehead"): n[i] += 1
        elif b["class"].startswith("rest"): r_[i] += 1
    counts = [{"notes": n[i], "rests": r_[i], "marks": []} for i in range(len(st))]
    ex, exr = DS.expects(counts)
    boxes, meta = E.detect_guided(M, big, ex, expect_rests=exr)
    tm = "models/omr_tie.pt"
    curves = DS.detect_curves(big, tm, ex, exr) if os.path.exists(tm) else None
    strict = cv.remove_staff_lines(ink, st, protect_noteheads=True)
    gray = np.asarray(big.convert("L")).astype("float32")
    d = DS.build_from(boxes, st, strict, sp, gray, counts, curves=curves, meta=meta)
    ck = CB.check(d, int(d.get("beats") or 4))
    bad = len(ck.get("over") or []) + len(ck.get("under") or [])
    # 쌓인 기둥 — 화음 학습이 먹혔는지
    heads = [b for b in boxes if b["class"].startswith("notehead")]
    heads.sort(key=lambda b: b["x"])
    g = []
    for b in heads:
        cx = b["x"] + b["w"] / 2
        if g and abs(cx - g[-1][-1]) < sp * 0.6: g[-1].append(cx)
        else: g.append([cx])
    return {"ok": ck.get("ok"), "bad": bad, "heads": len(heads),
            "cols": len(g), "stack": sum(1 for q in g if len(q) >= 2),
            "unrel": d.get("unreliable")}


MODELS = {"옛": YOLO(OLD), "새": YOLO(NEW)}
rows = []
for name, path in SHEETS:
    rec = {"page": name}
    for tag, M in MODELS.items():
        try:
            rec[tag] = run(M, path)
        except Exception as e:
            rec[tag] = {"err": f"{type(e).__name__}: {e}"[:60]}
    rows.append(rec); print(name, flush=True)
json.dump(rows, open("eval/cmp_models.json", "w"), ensure_ascii=False, indent=1)

ok = [r for r in rows if "err" not in r["옛"] and "err" not in r["새"]]
tot = lambda t, f: sum(r[t][f] for r in ok)
print(f"\n=== {len(ok)}장 ===")
for t in ("옛", "새"):
    print(f"  {t}모델: 맞음 {tot(t,'ok'):5} · 불일치 {tot(t,'bad'):4} · 머리 {tot(t,'heads'):6}")
up = [r for r in ok if r["새"]["bad"] < r["옛"]["bad"]]
dn = [r for r in ok if r["새"]["bad"] > r["옛"]["bad"]]
print(f"  좋아진 장 {len(up)} · 나빠진 장 {len(dn)} · 같음 {len(ok)-len(up)-len(dn)}")
so = sum(len((r["옛"].get("unrel") or {}).get("stacked") or []) for r in ok)
sn = sum(len((r["새"].get("unrel") or {}).get("stacked") or []) for r in ok)
print(f"  화음 판정 단: 옛 {so} → 새 {sn}")
